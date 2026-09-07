import { expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AccountMenuContent } from "./AccountMenu";

test("shows only the compact account identity and supported actions", () => {
  const markup = renderToStaticMarkup(
    <AccountMenuContent
      changePassword={vi.fn(async () => ({ ok: true } as const))}
      session={{
        displayLabel: "researcher",
        email: "researcher@example.test",
        operator: false,
        researcherId: "00000000-0000-4000-8000-000000000001",
      }}
      signOut={vi.fn(async () => ({ ok: true } as const))}
    />,
  );

  expect(markup).toContain('aria-label="Account menu"');
  expect(markup).not.toContain("aria-haspopup");
  expect(markup).toContain("researcher@example.test");
  expect(markup).toContain("Change password");
  expect(markup).toContain("Log out");
  expect(markup).not.toContain("Settings");
  expect(markup).not.toContain("Profile");
});
