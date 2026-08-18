"""Where a value of the technical description belongs.

The colour of a copy, its sound, the element it is and the format it
is on are four separate fields of the AVefi schema, and the four
vocabularies behind them share no value between them. That is worth
using: a term that is one of those values says by itself which field
it is destined for, and neither a mapping nor a profile has to keep a
second table in step with the schema.

Providers write these four into one field and call it different
things — ``lido:termMaterialsTech`` in a museum export, ``300 $b`` in
a library record — so the reading is the same everywhere and only the
place it is read from differs.

"""

from avefi_schema import model_pydantic_v2 as efi

#: AVefi value to the field it belongs in, with the wrapper class where
#: the field holds objects rather than a plain enum value. A value may
#: appear more than once only if the schema itself is ambiguous about
#: it, which the caller has to resolve.
TECHNICAL_TARGETS: dict[str, list] = {}

for _enum_name in dir(efi):
    if _enum_name == "ColourTypeEnum":
        _target, _wrapper = "has_colour_type", None
    elif _enum_name == "ItemElementTypeEnum":
        _target, _wrapper = "element_type", None
    elif _enum_name == "SoundTypeEnum":
        _target, _wrapper = "has_sound_type", None
    elif _enum_name.startswith("Format") and _enum_name.endswith("TypeEnum"):
        _target = "has_format"
        _wrapper = getattr(
            efi, _enum_name[len("Format") : -len("TypeEnum")], None
        )
        if _wrapper is None:
            continue
    else:
        continue
    for _member in getattr(efi, _enum_name):
        TECHNICAL_TARGETS.setdefault(_member.value, []).append(
            (_enum_name, _target, _wrapper)
        )
del _enum_name, _target, _wrapper, _member

#: Vocabularies that turn up in the same place and are recognised
#: without being acted on. Deriving a publication or a preservation
#: event from a note about the material of a copy would be a statement
#: about the film that the note does not make.
OUT_OF_SCOPE = {
    member.value: name
    for name in ("PublicationEventTypeEnum", "PreservationEventTypeEnum")
    for member in getattr(efi, name)
}


#: Colours that combine into one value rather than competing. A copy
#: described as black and white *and* colour is a copy with both, and
#: the schema has a value saying so; taking whichever was stated first
#: would throw away half of what the record says.
COMBINED_COLOURS = {
    frozenset({"BlackAndWhite", "Colour"}): "ColourBlackAndWhite",
    frozenset({"BlackAndWhite", "ColourBlackAndWhite"}): (
        "ColourBlackAndWhite"
    ),
    frozenset({"Colour", "ColourBlackAndWhite"}): "ColourBlackAndWhite",
}


def place_technical_value(item, target: str, value: str, wrapper) -> None:
    """Put one value of the technical description on a copy.

    A field holding several values does not repeat one it already has.
    A field holding one keeps the first stated, except where the
    schema has a value for the combination of the two.

    """
    if target == "has_format":
        if not any(existing.type == value for existing in item.has_format):
            item.has_format.append(wrapper(type=value))
        return
    current = getattr(item, target)
    if current is None:
        setattr(item, target, value)
        return
    if target == "has_colour_type" and str(current) != value:
        combined = COMBINED_COLOURS.get(frozenset({str(current), value}))
        if combined:
            setattr(item, target, combined)
