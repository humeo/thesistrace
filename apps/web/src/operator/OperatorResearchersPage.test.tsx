import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  OperatorResearchersView,
} from "./OperatorResearchersPage";
import {
  decodeResearcherPage,
} from "./operatorDirectoryClient";

const researcher = {
  active: true,
  created_at: "2026-08-20T06:00:00.000Z",
  current_session_count: 2,
  display_label: "Research Lead",
  email: "researcher@example.com",
  latest_successful_login_at: "2026-08-28T09:00:00.000Z",
  researcher_id: "00000000-0000-4000-8000-000000000001",
} as const;
const otherResearcher = {
  ...researcher,
  display_label: "Session Target",
  email: "target@example.com",
  researcher_id: "00000000-0000-4000-8000-000000000002",
} as const;

describe("Operator Researcher view", () => {
  it("decodes only the bounded read contract", () => {
    expect(decodeResearcherPage({
      items: [researcher],
      next_cursor: "researcher-cursor",
    })).toEqual({ items: [researcher], next_cursor: "researcher-cursor" });

    expect(() => decodeResearcherPage({
      items: [{ ...researcher, ip_address: "192.0.2.1" }],
      next_cursor: null,
    })).toThrow("Operator Researcher response is invalid");
  });

  it("renders Session revocation only for another Researcher with Sessions", () => {
    const markup = renderToStaticMarkup(
      <OperatorResearchersView
        operatorResearcherId={researcher.researcher_id}
        onResearcherNext={() => undefined}
        onResearcherPrevious={() => undefined}
        onSessionRevocation={() => undefined}
        onSearch={() => undefined}
        researcherCursorDepth={0}
        researchers={{ items: [researcher, otherResearcher], next_cursor: null }}
        search=""
      />,
    );

    expect(markup).toContain("Researchers");
    expect(markup).not.toContain("Invitations");
    expect(markup).toContain('aria-current="page" href="/operator/researchers"');
    expect(markup).toContain('href="/operator/data"');
    expect(markup).toContain("Research Lead");
    expect(markup).toContain("researcher@example.com");
    expect(markup).toContain("Current sessions");
    expect(markup).toContain("Latest login");
    expect(markup).toContain("researcher-details-");
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).toContain('aria-label="Search researchers"');
    expect(markup).not.toContain("Invite Researcher");
    expect(markup).not.toContain("Reissue");
    expect(markup).toContain("Current Operator");
    expect(markup).toContain("Revoke sessions");
    expect(markup).not.toContain('<p class="eyebrow">Operator Console</p>');
    expect(markup).not.toContain(
      "Review Researcher identity, current Login Sessions, and recent Invitation state.",
    );
    expect(markup).not.toContain("50 per page");
    expect(markup).not.toContain("Effective and terminal within 30 days");
    expect(markup).toContain(
      `aria-label="Revoke 2 Login Sessions for ${otherResearcher.email}"`,
    );
    expect(markup).not.toContain(
      `aria-label="Revoke 2 Login Sessions for ${researcher.email}"`,
    );
    expect(markup).not.toMatch(/Deactivate|Export|IP address|User-Agent/);
  });

  it("keeps the directory visible and disables every control while refreshing", () => {
    const markup = renderToStaticMarkup(
      <OperatorResearchersView
        operatorResearcherId={researcher.researcher_id}
        onResearcherNext={() => undefined}
        onResearcherPrevious={() => undefined}
        onSessionRevocation={() => undefined}
        onSearch={() => undefined}
        researcherCursorDepth={1}
        researchers={{ items: [researcher, otherResearcher], next_cursor: "researcher-next" }}
        search=""
        state="loading"
      />,
    );

    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Refreshing Operator Console…");
    expect(markup).toContain("Research Lead");
    expect(markup).toContain("researcher@example.com");
    expect(markup.match(/<(?:button|input)\b[^>]*\sdisabled=""/g)).toHaveLength(5);
  });
});
