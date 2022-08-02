from typing import Dict, Tuple, Optional, Any, IO

import os
import json
import tempfile
import logging

import ocrmypdf
from ocrmypdf import InputFileError, EncryptedPdfError

from pdfminer.high_level import extract_text as pdfminer_extract_text
from PIL import Image

from meine_stadt_transparent import settings
from mainapp.functions.document_parsing import cleanup_extracted_text

logger = logging.getLogger(__name__)

# This forces tesseract to use one core per page.
# os.environ["OMP_THREAD_LIMIT"] = "1"


class ParseError(RuntimeError):
    pass


class NoTextFoundException(ParseError):
    pass


def is_image(mime_type):
    return mime_type in [
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/bmp",
        "image/gif",
    ]


def get_dpi(image):
    try:
        with Image.open(image) as im:
            x, y = im.info["dpi"]
            return round(x)
    except Exception as e:
        logger.warning(f"Error while getting DPI from image {image}: {e}")
        return None


def calculate_a4_dpi(image):
    try:
        with Image.open(image) as im:
            width, height = im.size
            # divide image width by A4 width (210mm) in inches.
            dpi = int(width / (21 / 2.54))
            logger.debug(f"Estimated DPI {dpi} based on image width {width}")
            return dpi

    except Exception as e:
        logger.warning(f"Error while calculating DPI for image {image}: {e}")
        return None


def construct_ocrmypdf_parameters(
    input_file, mime_type, output_file, sidecar_file, safe_fallback=False
) -> Dict[str, Any]:
    ocrmypdf_args = {
        "input_file": input_file,
        "output_file": output_file,
        "jobs": settings.OCR_THREADS_PER_WORKER,
        "language": settings.OCR_LANGUAGE,
        "output_type": settings.OCR_OUTPUT_TYPE,
        "optimize": settings.OCR_OPTIMIZE,
        "progress_bar": True,
    }

    if settings.OCR_MODE == "force" or safe_fallback:
        ocrmypdf_args["force_ocr"] = True
    elif settings.OCR_MODE in ["skip", "skip_noarchive"]:
        ocrmypdf_args["skip_text"] = True
    elif settings.OCR_MODE == "redo":
        ocrmypdf_args["redo_ocr"] = True
    else:
        raise ParseError(f"Invalid ocr mode: {settings.OCR_MODE}")

    if settings.OCR_CLEAN == "clean":
        ocrmypdf_args["clean"] = True
    elif settings.OCR_CLEAN == "clean-final":
        if settings.OCR_MODE == "redo":
            ocrmypdf_args["clean"] = True
        else:
            ocrmypdf_args["clean_final"] = True

    if settings.OCR_DESKEW and not settings.OCR_MODE == "redo":
        ocrmypdf_args["deskew"] = True

    if settings.OCR_ROTATE_PAGES:
        ocrmypdf_args["rotate_pages"] = True
        ocrmypdf_args[
            "rotate_pages_threshold"
        ] = settings.OCR_ROTATE_PAGES_THRESHOLD  # NOQA: E501

    if settings.OCR_PAGES > 0:
        ocrmypdf_args["pages"] = f"1-{settings.OCR_PAGES}"
    else:
        # sidecar is incompatible with pages
        ocrmypdf_args["sidecar"] = sidecar_file

    if is_image(mime_type):
        dpi = get_dpi(input_file)
        a4_dpi = calculate_a4_dpi(input_file)
        if dpi:
            logger.debug(f"Detected DPI for image {input_file}: {dpi}")
            ocrmypdf_args["image_dpi"] = dpi
        elif settings.OCR_IMAGE_DPI:
            ocrmypdf_args["image_dpi"] = settings.OCR_IMAGE_DPI
        elif a4_dpi:
            ocrmypdf_args["image_dpi"] = a4_dpi
        else:
            raise ParseError(
                f"Cannot produce archive PDF for image {input_file}, "
                f"no DPI information is present in this image and "
                f"OCR_IMAGE_DPI is not set."
            )

    if settings.OCR_USER_ARGS and not safe_fallback:
        try:
            user_args = json.loads(settings.OCR_USER_ARGS)
            ocrmypdf_args = {**ocrmypdf_args, **user_args}
        except Exception as e:
            logger.warning(
                f"There is an issue with PAPERLESS_OCR_USER_ARGS, so "
                f"they will not be used. Error: {e}"
            )

    return ocrmypdf_args


def extract_text(pdf_file, sidecar_file=None):
    if sidecar_file and os.path.isfile(sidecar_file):
        with open(sidecar_file, "r") as f:
            text = f.read()

        if "[OCR skipped on page" not in text:
            # This happens when there's already text in the input file.
            # The sidecar file will only contain text for OCR'ed pages.
            logger.debug("Using text from sidecar file")

            return cleanup_extracted_text(text)
        else:
            logger.debug("Incomplete sidecar file: discarding.")

    # no success with the sidecar file, try PDF

    try:
        text = pdfminer_extract_text(pdf_file)
        stripped = cleanup_extracted_text(text)

        logger.debug(f"Extracted text from PDF file {pdf_file}")
        return stripped

    except Exception:
        # TODO catch all for various issues with PDFminer.six.
        #  If PDFminer fails, fall back to OCR.
        logger.warning(
            "Error while getting text from PDF document with " "pdfminer.six",
            exc_info=True,
        )

        # probably not a PDF file.
        return None


def ocr_document(
    file: IO[bytes], filename: str, mime_type: str, file_id: int
) -> Tuple[Optional[str], Optional[tempfile.TemporaryFile]]:

    if mime_type == "application/pdf" or mime_type.startswith("application/pdf;"):
        text_original = extract_text(file.name)
    elif mime_type == "text/text":
        text_original = file.read()
    else:
        text_original = None

    original_has_text = text_original and len(text_original) > 50

    if settings.OCR_MODE == "skip_noarchive" and original_has_text:
        logger.debug("Document has text, skipping OCRmyPDF entirely.")
        text = text_original
        return None, None

    archive_file = tempfile.NamedTemporaryFile()
    sidecar_file = tempfile.NamedTemporaryFile()

    args = construct_ocrmypdf_parameters(
        file.name, mime_type, archive_file.name, sidecar_file.name
    )

    try:
        logger.debug(f"Calling OCRmyPDF with args: {args}")
        ocrmypdf.ocr(**args)

        text = extract_text(archive_file.name, sidecar_file.name)

        if not text:
            raise NoTextFoundException("No text was found in the original document")

    except EncryptedPdfError:
        logger.warning(
            "This file is encrypted, OCR is impossible. Using "
            "any text present in the original file."
        )
        if original_has_text:
            text = text_original

    except (NoTextFoundException, InputFileError) as e:
        logger.warning(
            f"Encountered an error while running OCR: {str(e)}. "
            f"Attempting force OCR to get the text."
        )

        archive_path_fallback = tempfile.NamedTemporaryFile()
        sidecar_file_fallback = tempfile.NamedTemporaryFile()

        # Attempt to run OCR with safe settings.

        args = construct_ocrmypdf_parameters(
            file.name,
            mime_type,
            archive_path_fallback.name,
            sidecar_file_fallback.name,
            safe_fallback=True,
        )

        try:
            logger.debug(f"Fallback: Calling OCRmyPDF with args: {args}")
            ocrmypdf.ocr(**args)

            # Don't return the archived file here, since this file
            # is bigger and blurry due to --force-ocr.

            text = extract_text(archive_path_fallback, sidecar_file_fallback)

        except Exception as e:
            # If this fails, we have a serious issue at hand.
            raise ParseError(f"{e.__class__.__name__}: {str(e)}")

    except Exception as e:
        # Anything else is probably serious.
        raise ParseError(f"{e.__class__.__name__}: {str(e)}")

    # As a last resort, if we still don't have any text for any reason,
    # try to extract the text from the original document.
    if not text:
        if original_has_text:
            text = text_original
        else:
            logger.warning(
                f"No text was found in file {file_id}, the content will " f"be empty."
            )
            text = ""

    return text, archive_file
