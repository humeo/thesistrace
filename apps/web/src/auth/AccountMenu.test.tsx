import { expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { AccountMenuContent } from "./AccountMenu";

test("shows the avatar and username without email in the closed account trigger", () => {
  const markup = renderToStaticMarkup(
    <AccountMenuContent
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
  expect(markup).toContain('aria-haspopup="dialog"');
  expect(markup).toContain('class="account-avatar account-trigger-avatar"');
  expect(markup).toContain('class="account-trigger-name"');
  expect(markup).not.toContain("researcher@example.test");
  expect(markup).not.toContain("Change password");
  expect(markup).not.toContain("Settings");
  expect(markup).not.toContain("Profile");
});

test("keeps the current identity available before the menu opens", () => {
  const markup = renderToStaticMarkup(
    <AccountMenuContent
      session={{ displayLabel: "研究员", email: "researcher@example.test", operator: false,
        researcherId: "00000000-0000-4000-8000-000000000001" }}
      signOut={async () => ({ ok: true })}
    />,
  );
  expect(markup).toContain("研究员");
  expect(markup).toContain('aria-expanded="false"');
});
