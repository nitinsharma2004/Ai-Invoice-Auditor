from __future__ import annotations


 

import re

from datetime import date, datetime

from typing import Any


 

_ENGLISH_MONTHS = (

    "January",

    "February",

    "March",

    "April",

    "May",

    "June",

    "July",

    "August",

    "September",

    "October",

    "November",

    "December",

)


 

_SPANISH_MONTHS = {

    "enero": "January",

    "febrero": "February",

    "marzo": "March",

    "abril": "April",

    "mayo": "May",

    "junio": "June",

    "julio": "July",

    "agosto": "August",

    "septiembre": "September",

    "setiembre": "September",

    "octubre": "October",

    "noviembre": "November",

    "diciembre": "December",

}



 

def display_english_date(value: Any) -> str:

    if not value:

        return "—"


 

    if isinstance(value, (date, datetime)):

        return f"{value.day:02d} {_ENGLISH_MONTHS[value.month - 1]} {value.year}"


 

    value = str(value).strip()

    month_pattern = re.compile(

        r"\b(" + "|".join(_SPANISH_MONTHS) + r")\b",

        re.IGNORECASE,

    )

    value = month_pattern.sub(

        lambda match: _SPANISH_MONTHS[match.group(0).lower()],

        value,

    )


 

    try:

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        return f"{parsed.day:02d} {_ENGLISH_MONTHS[parsed.month - 1]} {parsed.year}"

    except ValueError:

        pass


 

    for date_format in (

        "%d de %B de %Y",

        "%d %B %Y",

        "%d-%B-%Y",

        "%d-%b-%Y",

        "%d/%m/%Y",

        "%d-%m-%Y",

    ):

        try:

            parsed = datetime.strptime(value, date_format)

            return f"{parsed.day:02d} {_ENGLISH_MONTHS[parsed.month - 1]} {parsed.year}"

        except ValueError:

            continue


 

    return value


 