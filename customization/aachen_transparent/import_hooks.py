from mainapp.models import AgendaItem
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

def sanitize_agenda_item(agenda_item: AgendaItem):
    
    # Aachen's RIS has some agenda items with a missing name attribute
    # break breaks the DB contraints
    if not agenda_item.name:
        agenda_item = "[missing name]"
