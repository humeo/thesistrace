import { createRoot } from "react-dom/client";
import { DailyTracksPage } from "../../src/daily-tracks/DailyTracksPage";
import { LanguageControls } from "./language-controls";

createRoot(document.getElementById("root")!).render(<><LanguageControls /><DailyTracksPage trackId="track_ui" /></>);
