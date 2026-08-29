import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  OperatorResearchersView,
} from "./OperatorResearchersPage";
import {
  decodeInvitationPage,
  decodeResearcherPage,
} from "./operatorDirectoryClient";

const invitation = {
  created_at: "2026-08-27T06:00:00.000Z",
  delivered_at: "2026-08-27T06:01:00.000Z",
  effective: true,
  email: "researcher@example.com",
  expires_at: "2026-08-29T06:00:00.000Z",
  invitation_id: "00000000-0000-4000-8000-000000000041",
  researcher_id: "00000000-0000-4000-8000-000000000001",
  status: "delivered",
  terminal_at: null,
} as const;

const researcher = {
  active: true,
  created_at: "2026-08-20T06:00:00.000Z",
  current_session_count: 2,
  display_label: "Research Lead",
  effective_invitation: invitation,
  email: "researcher@example.com",
  latest_successful_login_at: "2026-08-28T09:00:00.000Z",
  researcher_id: "00000000-0000-4000-8000-000000000001",
} as const;

describe("Operator Researcher view", () => {
  it("decodes only the bounded read contract", () => {
    expect(decodeResearcherPage({
      items: [researcher],
      next_cursor: "researcher-cursor",
    })).toEqual({ items: [researcher], next_cursor: "researcher-cursor" });
    expect(decodeInvitationPage({
      items: [invitation],
      next_cursor: null,
    })).toEqual({ items: [invitation], next_cursor: null });

    expect(() => decodeResearcherPage({
      items: [{ ...researcher, ip_address: "192.0.2.1" }],
      next_cursor: null,
    })).toThrow("Operator Researcher response is invalid");
    expect(() => decodeInvitationPage({
      items: [{ ...invitation, token_hash: "secret" }],
      next_cursor: null,
    })).toThrow("Operator Invitation response is invalid");
  });

  it("renders dense read-only Researcher and Invitation tables", () => {
    const markup = renderToStaticMarkup(
      <OperatorResearchersView
        invitationCursorDepth={0}
        invitations={{ items: [invitation], next_cursor: null }}
        onInvitationNext={() => undefined}
        onInvitationPrevious={() => undefined}
        onResearcherNext={() => undefined}
        onResearcherPrevious={() => undefined}
        onSearch={() => undefined}
        researcherCursorDepth={0}
        researchers={{ items: [researcher], next_cursor: null }}
        search=""
      />,
    );

    expect(markup).toContain("Researchers");
    expect(markup).toContain("Invitations");
    expect(markup).toContain("Research Lead");
    expect(markup).toContain("researcher@example.com");
    expect(markup).toContain("Current sessions");
    expect(markup).toContain("Latest login");
    expect(markup).toContain("Effective invitation");
    expect(markup).toContain('aria-label="Search researchers"');
    expect(markup).not.toMatch(/Revoke|Deactivate|Reissue|Export|IP address|User-Agent/);
  });

  it("keeps the directory visible and disables every control while refreshing", () => {
    const markup = renderToStaticMarkup(
      <OperatorResearchersView
        invitationCursorDepth={1}
        invitations={{ items: [invitation], next_cursor: "invitation-next" }}
        onInvitationNext={() => undefined}
        onInvitationPrevious={() => undefined}
        onResearcherNext={() => undefined}
        onResearcherPrevious={() => undefined}
        onSearch={() => undefined}
        researcherCursorDepth={1}
        researchers={{ items: [researcher], next_cursor: "researcher-next" }}
        search=""
        state="loading"
      />,
    );

    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Refreshing Operator Console…");
    expect(markup).toContain("Research Lead");
    expect(markup).toContain("researcher@example.com");
    expect(markup.match(/disabled=""/g)).toHaveLength(6);
  });
});
