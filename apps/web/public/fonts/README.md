# Product fonts

Locally served variable WOFF2 subsets, retrieved from Google Fonts on 2026-09-22.
No third-party requests are needed at runtime. `quantgrove.css` preserves the
upstream Unicode ranges and uses `font-display: swap`.

| Family | Weight range | License |
| --- | --- | --- |
| Inter | 400–700 | [SIL OFL](inter-OFL.txt) |
| Source Serif 4 | 400–600 | [SIL OFL](sourceserif4-OFL.txt) |
| Noto Sans SC | 400–700 | [SIL OFL](notosanssc-OFL.txt) |
| Noto Serif SC | 400–600 | [SIL OFL](notoserifsc-OFL.txt) |

Original CSS: https://fonts.googleapis.com/css2?family=Inter:wght@400..700&family=Noto+Sans+SC:wght@400..700&family=Noto+Serif+SC:wght@400..600&family=Source+Serif+4:wght@400..600&display=swap

Upstream sources and licenses: https://github.com/google/fonts/tree/main/ofl

`sources.json` records the exact source URL, file size and SHA-256 of each font.
The 215 files total approximately 10.4 MiB on disk; browsers download only the
Unicode subsets needed by the displayed text, not the entire collection.

## QAgentis editorial typography

The homepage uses the approved 2026-10-17 Modern Research Journal design at
https://qagentis-research-design.clarencereed.chatgpt.site/.
`source-serif-4-editorial.woff2` (Source Serif 4, variable 200–900) and
`noto-serif-sc-headings.woff2` (Noto Serif SC, variable 200–900, headline subset)
were exported from that design. Their SIL OFL licenses are included here.
The existing Noto Serif SC Unicode subsets cover other Chinese headings.

The shared wordmark preserves the original Source Serif 4 650, optical size 32
letter outlines and kerning in `src/brand/BrandWordmark.tsx`. The double-ring
mark geometry is unchanged. No remote font requests are needed at runtime.
