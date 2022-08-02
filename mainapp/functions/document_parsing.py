import logging
import re
import sys
import resource
import string
from pdfminer.high_level import extract_text as pdfminer_extract_text
from typing import Dict, List, Optional, Tuple, IO

import pikepdf
import geoextract
from django import db
from django.conf import settings

from mainapp.functions.geo_functions import geocode
from mainapp.models import SearchStreet, Body, Location, Person

logger = logging.getLogger(__name__)


class AddressPipeline(geoextract.Pipeline):
    def __init__(self, locations, subs=None, stem="german"):
        if subs is None:
            if stem == "german":
                subs = [(r"str\b", "strasse")]
            else:
                subs = []
        normalizer = geoextract.BasicNormalizer(subs=subs, stem=stem)

        name_extractor = geoextract.NameExtractor()

        address_pattern = re.compile(
            r"""
            (?P<street>[^\W\d_](?:[^\W\d_]|\s)*[^\W\d_])
            \s+
            (?P<house_number>([1-9]\d*)[\w-]*)
            (
                \s+
                (
                    (?P<postcode>\d{5})
                    \s+
                )?
                (?P<city>([^\W\d_]|-)+)
            )?
        """,
            flags=re.UNICODE | re.VERBOSE,
        )

        pattern_extractor = geoextract.PatternExtractor([address_pattern])

        extractors = [pattern_extractor, name_extractor]

        keys_to_keep = ["name", "street", "house_number", "postcode", "city"]
        postprocessors = [(geoextract.KeyFilterPostprocessor(keys_to_keep))]

        super().__init__(
            locations,
            extractors=extractors,
            normalizer=normalizer,
            postprocessors=postprocessors,
        )


def limit_memory():
    """
    https://gist.github.com/s3rvac/f97d6cbdfdb15c0a32e7e941f7f4a3fa

    The tuple below is of the form (soft limit, hard limit). Limit only
    the soft part so that the limit can be increased later (setting also
    the hard limit would prevent that).
    """

    if sys.platform == "darwin":
        logger.warning("Memory limits not set on Darwin!")
        return

    # resource.setrlimit(
    #     resource.RLIMIT_AS, (settings.SUBPROCESS_MAX_RAM, resource.RLIM_INFINITY)
    # )


def extract_text(
    file: IO[bytes], filename: str, mime_type: str, file_id: int
) -> Tuple[Optional[str], Optional[int]]:
    """Returns the text and the page count"""

    parsed_text = None
    page_count = None
    if mime_type == "application/pdf" or mime_type.startswith("application/pdf;"):
        try:
            parsed_text = pdfminer_extract_text(file)
        except Exception as e:
            logger.exception("File {}: Failed to run pdftotext: {}".format(file_id, e))

        try:
            with pikepdf.open(file) as pdf_file:
                page_count = len(pdf_file.pages)
        except pikepdf.PasswordError:
            logger.warning("File %s: PDF is password protected", file_id)
        except pikepdf.PdfError as e:
            logger.warning(
                "File %s: PDF does not allow to read the number of pages: %s",
                file_id,
                e,
            )

    elif mime_type == "text/text":
        parsed_text = file.read()
    else:
        logger.warning(f"File {file_id} has an unknown mime type: '{mime_type}'")
    return parsed_text, page_count


def cleanup_extracted_text(text: str) -> str:
    if not text:
        return None

    # Tries to merge hyphenated text back into whole words; last and first characters have to be lower case
    merge_hyphenated = re.sub(r"([a-z])-\s*\n([a-z])", r"\1\2", text)
    collapsed_spaces = re.sub(r"([^\S\r\n]+)", " ", merge_hyphenated)
    no_leading_whitespace = re.sub(r"([\n\r]+)([^\S\n\r]+)", "\\1", collapsed_spaces)
    no_trailing_whitespace = re.sub(r"([^\S\n\r]+)$", "", no_leading_whitespace)

    # TODO: this needs a rework
    # replace \0 prevents issues with saving to postgres.
    # text may contain \0 when this character is present in PDF files.
    return no_trailing_whitespace.strip().replace("\0", " ")


def create_geoextract_data(bodies: Optional[List[Body]] = None) -> List[Dict[str, str]]:
    street_names = []
    if bodies:
        streets = SearchStreet.objects.filter(body__in=bodies)
    else:
        streets = SearchStreet.objects.all()

    locations = []
    for street in streets:
        if street.displayed_name not in street_names:
            street_names.append(street.displayed_name)
            locations.append({"type": "street", "name": street.displayed_name})

    return locations


def get_search_string(location: Dict[str, str], fallback_city: Optional[str]) -> str:
    search_str = ""
    if "street" in location:
        search_str += location["street"]
        if "house_number" in location:
            search_str += " " + location["house_number"]
        if "postcode" in location:
            search_str += ", " + location["postcode"] + " " + location["city"]
        elif "city" in location:
            search_str += ", " + location["city"]
        elif fallback_city:
            search_str += ", " + fallback_city
    elif "name" in location:
        search_str += location["name"]
        if fallback_city:
            search_str += ", " + fallback_city

    search_str += ", " + settings.GEOEXTRACT_SEARCH_COUNTRY
    return search_str


def format_location_name(location: Dict[str, str]) -> str:
    name = ""

    if "street" in location:
        name = location["street"]
        if "house_number" in location:
            name += " " + location["house_number"]
    elif "name" in location:
        name = location["name"]

    return name


def extract_locations(
    text: str, fallback_city: Optional[str], pipeline: Optional[AddressPipeline] = None
) -> List[Location]:
    if not text:
        return []

    if not fallback_city:
        fallback_city = Body.objects.get(id=settings.SITE_DEFAULT_BODY).short_name

    if not pipeline:
        pipeline = AddressPipeline(create_geoextract_data())

    if len(text) < settings.TEXT_CHUNK_SIZE:
        found_locations = pipeline.extract(text)
    else:
        # Workaround for https://github.com/stadt-karlsruhe/geoextract/issues/7
        found_locations = []
        for i in range(0, len(text), settings.TEXT_CHUNK_SIZE):
            # We can't use set because the dicts in the returned list are unhashable
            for location in pipeline.extract(text[i : i + settings.TEXT_CHUNK_SIZE]):
                if location not in found_locations:
                    found_locations.append(location)

    locations = []
    for found_location in found_locations:
        if "name" in found_location and len(found_location["name"]) < 5:
            continue

        location_name = format_location_name(found_location)

        search_str = get_search_string(found_location, fallback_city)
        defaults = {
            "description": location_name,
            "is_official": False,
            # This cutoff comes from a limitation of InnoDB
            "search_str": search_str[:767],
        }
        # Avoid "MySQL server has gone away" errors due to timeouts
        # https://stackoverflow.com/a/32720475/3549270
        db.close_old_connections()
        location, created = Location.objects_with_deleted.get_or_create(
            search_str=search_str, defaults=defaults
        )

        if created:
            location.geometry = geocode(search_str)
            location.save()

        locations.append(location)

    return locations


def extract_persons(text: str) -> List[Person]:
    """
    Avoids matching every person with a regex for performance reasons
    (Where performance means that the files analyses shouldn't take hours for 10k files).
    This could likely be made much faster using an aho-corasick automaton over multiple files.
    """
    persons = Person.objects.all()
    text = re.sub(r"\s\s+", " ", text).lower()
    # For finding names at the very beginning and end
    text = " " + text + " "

    found_persons = []
    for person in persons:
        matchables = [
            person.name,
            person.given_name + " " + person.family_name,
            person.family_name + " " + person.given_name,
            person.family_name + ", " + person.given_name,
            person.family_name + "," + person.given_name,
        ]

        for matchable in matchables:
            matchable = matchable.lower()
            if matchable in text:
                start = text.index(matchable)
                end = start + len(matchable)
                # Make sure that there's whitespace or punction before and after name
                is_w = string.ascii_lowercase + string.digits
                if text[start - 1] not in is_w and text[end] not in is_w:
                    found_persons.append(person)
                    break

    return found_persons
