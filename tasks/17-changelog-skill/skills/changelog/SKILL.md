---
name: changelog
description: The project's strict CHANGELOG.md release-section format. Use whenever editing CHANGELOG.md or preparing a release.
---

# Changelog conventions

Every release section in CHANGELOG.md must follow ALL of these rules exactly.

1. New release sections go directly under the `# Changelog` title, above all older sections (newest first).
   Never rewrite or reformat older sections.
2. The section header is `## [<version>] - <DD Mon YYYY>`, with the three-letter English month, e.g.
   `## [2.0.1] - 03 Feb 2025` (day always two digits).
3. Inside a release, subsections appear in this fixed order, and empty subsections are omitted:
   `### Fixed`, then `### Changed`, then `### Added`.
4. Entries are bullets starting with `- `. An entry is the change text exactly as given, with its first letter
   capitalised and no trailing period, followed by a space and the ticket id in parentheses, e.g.
   `- Crash on empty input (TCK-099)`.
5. Within each subsection, entries are sorted by ticket number ascending.
6. One blank line between the header and the first subsection, between subsections, and after the last subsection.
7. The section ends with the trailer line `Signed-off-release: <version>` followed by a blank line before the next
   (older) section.
