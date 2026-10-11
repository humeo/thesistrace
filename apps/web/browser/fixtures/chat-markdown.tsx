import { createRoot } from "react-dom/client";
import { useState } from "react";
import { AssistantMarkdown } from "../../src/chat/ChatTimeline";
import { ChatUiProvider } from "../../src/chat/ChatUiProvider";
import "../../src/styles.css";

const source = "from quantgrove import Targets\n\n\ndef compute(data, state):\n    return Targets.equal_weight(\n        data.eligible,\n        update=(data.session_index % 5 == 0) & data.eligible.any(axis=0),\n        reason='Equal-weight eligible universe; rebalance every 5 sessions',\n    )\n";
const params = new URLSearchParams(location.search);
const streaming = params.get("streaming") === "true";
const language = params.get("language");

function Fixture() {
  const [complete, setComplete] = useState(!streaming);
  const content = language === null
    ? "### Python 策略\n\n保留 **原始代码** 与 `data.eligible`。\n\n```python\n"
      + (complete ? source + "```\n\n| 状态 | 说明 |\n| --- | --- |\n| 完成 | 保留源码 |" : source.slice(0, source.indexOf("        update=")))
    : "```" + language + "\nx < y && y > z\n    **keep literal**\n\ttab-indented\nlong line: " + "x".repeat(160) + "\n```";
  return <ChatUiProvider><main className="quantgrove-chat" style={{ maxWidth: 808, margin: "auto", padding: 20 }}>
    <AssistantMarkdown content={content} streaming={!complete} />
    {streaming && <button onClick={() => setComplete(true)}>Complete stream</button>}
  </main></ChatUiProvider>;
}

createRoot(document.getElementById("root")!).render(<Fixture />);
