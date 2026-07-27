# MARC21 to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.marc21.mapping`;
do not edit by hand.

| Rule | Level | MARC21 source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `moving_image_filter` | Record | `leader/06, 006/00, 007/00, 008/33` | `—` | Profile vocabulary | Only projected medium and videorecording records are in scope. A record describing a filmstrip, a slide set or a book is skipped and reported, and so is a projected medium record that says nothing about which medium it is |
| `record_id` | Item | `001, prefixed with the assigning agency in 003, else 035$a` | `has_identifier, described_by.has_source_key` | — | Written as (agency)number, the form MARC itself uses in 035$a. A record without any identifier is skipped and reported, because its records could not be referred to |
| `work_type` | Work | `leader/07` | `type` | Profile bibliographic_level_map | Bibliographic level; an unmapped level falls back to Monographic and is reported |
| `work_grouping` | Work | `primary title, director, production date` | `has_identifier (work)` | Profile work_key_fields | Several copies of one film share one WorkVariant; set work_key_fields to () for one work per record |
| `manifestation_grouping` | Manifestation | `work key plus colour, sound, format and languages of the copy` | `has_identifier (manifestation)` | — | Copies agreeing on the carrier characteristics share a manifestation |
| `primary_title` | Work, Manifestation, Item | `245$a$b$n$p with the nonfiling character count in ind2` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Nonfiling indicator, else article handling | ind2 states how many leading characters are not to be sorted on, which is better evidence than an article list; a fully bracketed title becomes SuppliedDevisedTitle |
| `alternative_title` | Work | `246$a$b$n$p, 247$a$b` | `has_alternative_title` | Article handling in both directions | The distinction MARC draws in 246 ind2 and the former title semantics of 247 have no AVefi counterpart and are reported |
| `production_date` | Work | `008/06 date type with 008/07-10 and 008/11-14, else 264 ind2=0 $c` | `has_event.has_date` | ISODate | The date type decides how the two dates are read; p and r put the release date first and the production date second |
| `production_place` | Work | `257$a, 264 ind2=0 $a` | `has_event.located_in.has_name` | — | — |
| `production_credits` | Work | `100, 110, 700, 710 with a relator code in $4 or a relator term in $e` | `has_event.has_activity` | Profile relator_activities | An agent without a relator, or with a relator that has no AVefi activity, is reported rather than filed under a guessed activity |
| `publication_statement` | Manifestation | `260$a$b$c, 264 ind2=1 and ind2=2 $a$b$c, 008 release date` | `has_event (PublicationEvent)` | ISODate | ind2=2 becomes a DistributionEvent, everything else a ReleaseEvent; manufacture and copyright statements are reported instead, see the assumptions |
| `edition` | Manifestation | `250$a$b` | `has_note` | — | AVefi has no edition field, so the statement is kept as a note |
| `duration` | Item | `306$a, else 008/18-20, else the running time in 300$a` | `has_duration.has_value` | ISODurationInHours | 008/18-20 holds the running time in minutes; sources that disagree are reported and the most precise one wins |
| `extent` | Item | `300$a length in feet or metres` | `has_extent` | — | Only feet and metres have an AVefi unit; a reel count has none and stays in the note |
| `language` | Item | `008/35-37, 041$a, 041$j` | `in_language` | ISO 639-2/B | 041$a is read as spoken language and 041$j as subtitles; 041$b and 041$h are reported |
| `colour_type` | Item | `007/03` | `has_colour_type` | Profile colour_type_map | — |
| `sound_type` | Item | `007/05` | `has_sound_type` | Profile sound_type_map | A blank at this position means silent rather than uncoded |
| `format` | Item | `007/07 for a motion picture, 007/04 for a videorecording` | `has_format (Film, Video)` | Profile film_gauge_map, video_format_map | The positions differ between the two categories of 007, so 007/00 has to be read before either of them |
| `dimensions` | Item | `300$c` | `has_format (Film, Video)` | Profile dimension_format_map | Consulted only when 007 yielded no format |
| `access_status` | Item | `007/11 generation, motion pictures only` | `has_access_status` | Profile generation_access_map | — |
| `genre` | Work | `655$a` | `has_genre.has_name` | Profile genre_source_vocabularies | Subdivisions in $v$x$y$z are reported, as AVefi has no place for them |
| `notes` | Item | `300, 500, 508, 511, 546` | `has_note` | — | Credits and cast are kept verbatim, because free text cannot be split into agents and activities reliably |
| `holdings` | Item | `852$a$b$c$h$j$p` | `has_note, has_identifier` | — | The shelving control number in $j becomes a second local identifier, qualified with the institution in $a; the field as a whole becomes a note |
| `technique` | Work | `008/34` | `—` | — | Animation and live action have no AVefi counterpart and are reported |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Taken from the profile, not from 003 or 852$a, so that the issuer is unambiguous; the shipped default is a placeholder and using it is reported once per run |

## Assumptions

Decisions the mapping takes that MARC21 does not determine, and that need confirming against the reference data:

- This is a format converter, not an institution converter. The shipped profile carries a placeholder issuer, and every run using it reports a warning: the ISIL of the holding institution has to be configured before the records are used. No ISIL is ever derived from 003 or 852$a, because an agency code identifies the cataloguing agency rather than the holder.
- Only records whose leader position 06 is `g`, projected medium, are considered, and of those only the ones that 007/00 or 008/33 identify as a motion picture or a videorecording. A projected medium record saying nothing about which medium it is, which would equally be a filmstrip or a slide set, is skipped with a warning rather than imported as a film.
- `245 ind2` gives the number of leading characters not to be sorted on. It is used for `has_ordering_name` in preference to the article list of `core.normalise.normalise_title`, because the cataloguer stated the article rather than a list guessing it. The article list is used only where the indicator is 0, which is also what a record without an article carries, so a title with an article and an indicator of 0 is treated as if it had no article.
- A title enclosed in brackets as a whole is a devised title and becomes `SuppliedDevisedTitle` with the brackets removed. The nonfiling count is reduced by one accordingly.
- Trailing ISBD punctuation (` / : ; , =`) is display markup and is removed, from a title as well as from a name. A trailing full stop is removed only where the preceding character is not a capital letter, so that an abbreviated forename keeps its stop. Without this, `Die Brücke` and `Die Brücke.` would be two works rather than one.
- The 008 date type in position 06 decides how positions 07-10 and 11-14 are read. `s` is a production date, `e` a detailed production date, `m`, `i`, `k`, `c`, `d` and `u` an interval, `q` an interval qualified as questionable, and `p` and `r` put the release date in the first and the production date in the second position. A date type that is not one of these is reported and only the first date is used.
- A date containing `u`, such as `196u`, states a decade in a notation ISODate cannot express. It is reported and left unset rather than widened to an interval, which would assert a precision the record does not have. `9999` in the second date marks an open ended range and yields no end date.
- Copyright statements, that is `264 ind2=4` and the second date of date type `t`, are reported and not mapped: RightsCopyrightRegistrationEvent requires a copyright activity with an agent, and MARC does not reliably supply one. Manufacture statements in `264 ind2=3` are reported for the same reason, ManufactureEvent having no generic type value.
- 008 positions 18-20 hold the running time of a moving image in minutes. `000` means that it exceeds three digits and `nnn` that it does not apply; both yield no duration. Where 306$a and the fixed field disagree, 306$a wins because it is precise to the second, and the divergence is reported.
- A blank in 007 position 05 means silent, not uncoded, so the profile vocabulary is consulted before a position is dismissed as a fill character. Everywhere else a blank, a vertical bar or a hash means that nothing was coded and is passed over silently.
- The character positions of 007 depend on 007/00. For a motion picture position 04 is the presentation format and 07 the film gauge; for a videorecording 04 is the videorecording format and 07 the tape width. Only the gauge and the videorecording format are mapped.
- Of 007 only the positions named in the mapping table are consulted. The remaining positions, such as the base of the film or the configuration of playback channels, have no AVefi counterpart and are out of scope rather than reported per record.
- Free text notes are kept verbatim and prefixed with a label naming the field they came from, because a note detached from its field is not intelligible. Production credits in 508 and cast in 511 are kept as notes rather than parsed into agents: splitting a credit line into names and functions cannot be done reliably, and a wrong activity is worse than a visible note.
- The physical description in 300 is kept as a note in full, in addition to the duration, extent and format derived from it, so that nothing of it is lost to the partial parsing.
- Life dates in $d of an agent field are reported, AVefi Agent having no field for them.
- Every record in scope yields one item. Works and manifestations are shared between records according to the profile key.
