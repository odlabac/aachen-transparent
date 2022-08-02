import logging
import tempfile
import shutil
from tqdm import tqdm
from minio.commonconfig import CopySource
import minio.error

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from mainapp.functions.document_parsing import (
    extract_persons,
    extract_locations,
    cleanup_extracted_text,
)
from mainapp.functions.ocr import ocr_document
from mainapp.functions.minio import minio_client, minio_file_bucket
from mainapp.models import File, Body

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "OCRs and analyzes files and writes the result back to the database"

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, help="OCR the file with the given ID")
        parser.add_argument(
            "--all",
            dest="all",
            action="store_true",
            help="Overwrite existing extracted text",
        )
        parser.add_argument(
            "--empty",
            dest="all_empty",
            action="store_true",
            help="OCR files with empty parsed_text",
        )

    def parse_file(self, file: File):
        pdf_file = tempfile.NamedTemporaryFile()

        try:
            with self.mc.get_object(minio_file_bucket, str(file.id)) as obj:
                total_size = int(obj.headers["Content-length"])
                with tqdm.wrapattr(obj, "read", total=total_size) as obj:
                    shutil.copyfileobj(obj, pdf_file)

                ocr_text, ocr_file = ocr_document(
                    pdf_file, file.name, file.mime_type, file.id
                )

                if ocr_file is not None and settings.OCR_REPLACE_FILE:
                    self.mc.put_object(
                        minio_file_bucket,
                        str(file.id),
                        ocr_file.file,
                        ocr_file.filesize,
                        content_type=file.mime_type,
                    )

            if not ocr_text:
                logger.warning("Nothing recognized")
                return

            file.parsed_text = cleanup_extracted_text(ocr_text)
            file.mentioned_persons.set(
                extract_persons(file.name) + extract_persons(ocr_text)
            )
            file.locations.set(extract_locations(file.parsed_text, self.fallback_city))

            print(file.mentioned_persons.all())
            print()
            print(file.locations.all())

            file.save()

        except minio.error.S3Error as e:
            if e.code == "NoSuchKey":
                logger.warning(
                    "Missing object for file: %s (%s, %s). Skipping...",
                    file.id,
                    file.oparl_id,
                    file.name,
                )

    def handle(self, *args, **options):
        self.fallback_city = Body.objects.get(id=settings.SITE_DEFAULT_BODY).short_name
        self.mc = minio_client()

        if options["all_empty"]:
            files = File.objects.filter(
                Q(parsed_text="") | Q(parsed_text__isnull=True)
            ).all()

        elif options["all"]:
            files = File.objects.all()

        elif options["id"]:
            file = File.objects.get(id=options["id"])
            files = [file]

        with tqdm(files) as files_pbar:
            for file in files_pbar:
                files_pbar.set_description(f"{file.id}: {file.name}")

                try:
                    self.parse_file(file)
                except Exception as e:
                    logger.error(f"Error parsing file {file.id}:")
                    logger.exception(e)
