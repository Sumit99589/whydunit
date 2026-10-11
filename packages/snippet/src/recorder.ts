// The rrweb recorder, shipped as a separate script so only sampled sessions download it.
import { record } from "@rrweb/record";

(window as unknown as { __whydunitRecord?: typeof record }).__whydunitRecord = record;
