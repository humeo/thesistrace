export const operatorResearchersEn = {
  navigation: { sections: "Operator Console sections", researchers: "Researchers", data: "Data" },
  code: {
    label: "Verification code", sending: "Sending…", resend: "Resend code", send: "Send confirmation code",
    sent: "A code was sent to your account email. It expires in 5 minutes.", failed: "Code could not be sent. Please wait and try again.",
  },
  common: { cancel: "Cancel", effect: "Effect", emailConfirmation: "Email confirmation", targetEmail: "Target email", accessLost: "Operator access is no longer available.", invalidOtp: "The verification code is incorrect or has expired.", invalidProof: "Confirmation expired or was already used. Submit again.", rateLimited: "Too many confirmation attempts. Wait one minute and try again." },
  session: {
    eyebrow: "Session revocation", title: "Revoke Login Sessions?", description: "Confirm the exact Researcher before removing every current Login Session.",
    researcher: "Researcher", researcherId: "Researcher ID", current: "Current Login Sessions",
    effect: "Every current Login Session for this Researcher will be revoked. The Researcher remains active and can sign in again.",
    revoking: "Revoking…", revoke: "Revoke sessions", failed: "Login Sessions could not be revoked. Try again.",
    protectedTarget: "The current Operator's Login Sessions cannot be revoked here.", invalidTarget: "This Researcher is no longer available. Refresh the Console.",
    requestInvalid: "The Session revocation request is invalid. Refresh the Console.", unavailable: "Session service is unavailable. Try again.",
  },
  directory: {
    notFound: "Not found", notFoundDescription: "The requested resource is not available.",
    pageLabel: "Operator Researchers", title: "Researcher access", researchers: "Researchers",
    searchResearchers: "Search researchers", searchPlaceholder: "Canonical email or display label", search: "Search",
    sessionsRevoked_one: "Revoked {{countLabel}} Login Session for {{email}}.", sessionsRevoked_other: "Revoked {{countLabel}} Login Sessions for {{email}}.",
    refreshing: "Refreshing Operator Console…", loading: "Loading Operator Console…", unavailable: "Operator Console unavailable.", stale: " Displayed data may be stale.", retry: "Retry",
    researchersUnavailable: "Researchers unavailable.", researchersLoading: "Loading Researchers…", noResearchers: "No Researchers found.",
    researcher: "Researcher", researcherId: "Researcher ID", access: "Access", created: "Created", latestLogin: "Latest login", currentSessions: "Current sessions", sessionAction: "Session action", details: "Details",
    active: "Active", inactive: "Inactive", never: "Never", currentOperator: "Current Operator", noActiveSessions: "No active Sessions", revokeSessions: "Revoke sessions", revokeSessionsAria: "Revoke {{count}} Login Sessions for {{email}}",
    email: "Email", state: "State", action: "Action",
    pagination: "{{label}} pagination", previous: "Previous", next: "Next", page: "Page {{page}}",
  },
} as const;

export const operatorResearchersZh = {
  navigation: { sections: "Operator 控制台分区", researchers: "研究员", data: "数据" },
  code: {
    label: "验证码", sending: "发送中…", resend: "重新发送验证码", send: "发送确认验证码",
    sent: "验证码已发送至账户邮箱，5 分钟内有效。", failed: "验证码发送失败。请稍后重试。",
  },
  common: { cancel: "取消", effect: "操作影响", emailConfirmation: "邮箱确认", targetEmail: "目标邮箱", accessLost: "Operator 权限已不可用。", invalidOtp: "验证码错误或已过期。", invalidProof: "确认凭证已过期或已使用，请重新提交。", rateLimited: "确认尝试次数过多。请等待一分钟后重试。" },
  session: {
    eyebrow: "撤销会话", title: "撤销登录会话？", description: "移除所有当前登录会话前，请确认目标研究员。",
    researcher: "研究员", researcherId: "研究员 ID", current: "当前登录会话",
    effect: "将撤销此研究员当前的所有登录会话。研究员账户仍可用，可以再次登录。",
    revoking: "撤销中…", revoke: "撤销会话", failed: "无法撤销登录会话，请重试。",
    protectedTarget: "不能在此撤销当前 Operator 的登录会话。", invalidTarget: "此研究员已不可用，请刷新控制台。",
    requestInvalid: "会话撤销请求无效，请刷新控制台。", unavailable: "会话服务不可用，请重试。",
  },
  directory: {
    notFound: "未找到", notFoundDescription: "请求的资源不可用。",
    pageLabel: "Operator 研究员", title: "研究员访问权限", researchers: "研究员",
    searchResearchers: "搜索研究员", searchPlaceholder: "规范化邮箱或显示名称", search: "搜索",
    sessionsRevoked_one: "已撤销 {{email}} 的 {{countLabel}} 个登录会话。", sessionsRevoked_other: "已撤销 {{email}} 的 {{countLabel}} 个登录会话。",
    refreshing: "正在刷新 Operator 控制台…", loading: "正在加载 Operator 控制台…", unavailable: "Operator 控制台不可用。", stale: " 显示的数据可能已过时。", retry: "重试",
    researchersUnavailable: "研究员列表不可用。", researchersLoading: "正在加载研究员…", noResearchers: "未找到研究员。",
    researcher: "研究员", researcherId: "研究员 ID", access: "访问权限", created: "创建时间", latestLogin: "最近登录", currentSessions: "当前会话", sessionAction: "会话操作", details: "详情",
    active: "启用", inactive: "停用", never: "从未", currentOperator: "当前 Operator", noActiveSessions: "无活动会话", revokeSessions: "撤销会话", revokeSessionsAria: "撤销 {{email}} 的 {{count}} 个登录会话",
    email: "邮箱", state: "状态", action: "操作",
    pagination: "{{label}} 分页", previous: "上一页", next: "下一页", page: "第 {{page}} 页",
  },
} as const;
