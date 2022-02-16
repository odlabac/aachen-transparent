"""
Using this file, you can attach sanitize-callbacks to the importer. The following functions can be used:
- sanitize_file
- sanitize_person
- sanitize_consultation
- sanitize_meeting
- sanitize_agenda_item
- sanitize_paper
- sanitize_organization

To activate these callbacks, you need to register this file as described in the readme.
"""

import mainapp.models as models

RIS_BASEURL = "https://ratsinfo.aachen.de"


def sanitize_common(obj):
    sanitize_web(obj)


def sanitize_web(obj):
    if obj.web:
        return

    if isinstance(obj, models.Person):
        obj.web = f"{RIS_BASEURL}/bi/kp020.asp?KPLFDNR={obj.allris_id}"
    elif isinstance(obj, models.Meeting):
        obj.web = f"{RIS_BASEURL}/bi/to010.asp?SILFDNR={obj.allris_id}"
    elif isinstance(obj, models.Paper):
        obj.web = f"{RIS_BASEURL}/bi/vo020.asp?VOLFDNR={obj.allris_id}"
    elif isinstance(obj, models.AgendaItem):
        obj.web = f"{RIS_BASEURL}/bi/to020.asp?TOLFDNR={obj.allris_id}"
    elif isinstance(obj, models.Organization):
        obj.web = f"{RIS_BASEURL}/bi/au020.asp?AULFDNR={obj.allris_id}"


def sanitize_agenda_item(obj: models.AgendaItem):
    sanitize_common(obj)

    # Aachen's RIS has some agenda items with a missing name attribute
    # break breaks the DB contraints
    if not obj.name:
        obj = "[missing name]"


def sanitize_file(obj: models.File):
    sanitize_common(obj)


def sanitize_person(obj: models.Person):
    sanitize_common(obj)


def sanitize_consultation(obj: models.Consultation):
    sanitize_common(obj)


def sanitize_meeting(obj: models.Meeting):
    sanitize_common(obj)


def sanitize_paper(obj: models.Paper):
    sanitize_common(obj)


def sanitize_organization(obj: models.Organization):
    sanitize_common(obj)
