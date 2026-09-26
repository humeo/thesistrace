import "../../src/styles.css";
import { createRoot } from "react-dom/client";
import { DailyTracksPage } from "../../src/daily-tracks/DailyTracksPage";
import { LanguageControls } from "./language-controls";

createRoot(document.getElementById("root")!).render(<><LanguageControls /><DailyTracksPage trackId={new URL(window.location.href).searchParams.has("list") ? undefined : "track_ui"} /></>);
