import { rmSync } from "node:fs";
import { resolve } from "node:path";

rmSync(resolve(".test-workspace"), { recursive: true, force: true });
