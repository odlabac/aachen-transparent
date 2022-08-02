from concurrent.futures import ThreadPoolExecutor
from abc import ABC
from typing import Tuple, Dict, Any

from django.conf import settings
from django.core.management.base import BaseCommand

from importer.executor import SingleThreadExecutor, WorkerPoolExecutor
from importer.importer import Importer
from importer.loader import get_loader_from_body
from mainapp.models import Body


class ImportBaseCommand(BaseCommand, ABC):
    def add_arguments(self, parser):
        parser.add_argument("--body", help="The oparl id of the body", type=str)
        parser.add_argument(
            "--ignore-modified",
            help="Do not update modified files in the database",
            action="store_true",
        )
        parser.add_argument(
            "--singlethread",
            action="store_const",
            const=SingleThreadExecutor,
            dest="executor",
            help="Force execution to run within a single thread",
        )
        parser.add_argument(
            "--worker",
            action="store_const",
            const=WorkerPoolExecutor,
            dest="executor",
            help="Execute using a cluster of workers and the Django queue",
        )
        parser.add_argument(
            "--skip-download",
            action="store_true",
            dest="skip_download",
            default=False,
            help="Do not download and parse the files",
        )

    def get_importer(self, options: Dict[str, Any]) -> Tuple[Importer, Body]:
        if options.get("body"):
            body = Body.objects.get(oparl_id=options["body"])
        else:
            body = Body.objects.get(id=settings.SITE_DEFAULT_BODY)

        executor = options["executor"]
        if executor is None:
            executor = ThreadPoolExecutor

        kwargs = {
            "executor": executor,
            "update_modified": not options.get("ignore_modified", False),
            "download_files": not options.get("skip_download", False),
        }

        if body.oparl_id is not None:
            loader = get_loader_from_body(body.oparl_id)
            importer = Importer(loader, body, **kwargs)
        else:
            importer = Importer(**kwargs)

        return importer, body
