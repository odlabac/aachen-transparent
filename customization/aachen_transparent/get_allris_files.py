from urllib.request import urlopen
from bs4 import BeautifulSoup
from typing import Union

BASE_URL = 'https://ratsinfo.aachen.de'

UrlOrLfdnr = Union[str, int]

# Get Beschlüsse

def allris_url(lfdnr: int, obj: str = 'paper'):
    if obj == 'paper':
        return f'{BASE_URL}/bi/vo020.asp?VOLFDNR={lfdnr}'
    elif obj == 'file':
        return f'{BASE_URL}/bi/do027.asp?DOLFDNR={lfdnr}'

def load(url: str) -> BeautifulSoup:
    with urlopen(url) as f:
        return BeautifulSoup(f, 'html.parser')



# 'https://ratsinfo.aachen.de/bi/vo020.asp?VOLFDNR=86'
def get_paper_files(url: UrlOrLfdnr):
    if isinstance(url, int):
        url = allris_url(url, 'paper')

    soup = load(url)

    forms = soup.find_all('form', action='do027.asp')

    for form in forms:
        lfdnr = int(form.find('input', attrs={'name': 'DOLFDNR'})['value'])
        type = form.find('input', type='submit')['value']

        print(lfdnr, type)

        with get_document(lfdnr, 'html') as f:
            print(f.read())

def get_agenda_item_resolution(url: UrlOrLfdnr):
    pass

# Get document
# https://ratsinfo.aachen.de/bi/do027.asp?DOLFDNR=38&options=64
#
# options=0 -> HTML
#         64 -> PDF
#         128 -> XML?
#
# annots=1
def get_document(url: UrlOrLfdnr, format: str):
    if isinstance(url, int):
        url = allris_url(url, 'file')

    options = 0
    if format == 'pdf':
        options += 64

    url += f'&options={options}'

    return urlopen(url)

if __name__ == '__main__':
    # get_paper_files(86)

    get_agenda_item_resolution(334)
