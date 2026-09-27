import { Config } from '@remotion/cli/config';

// UI matni (kassa raqamlari) JPEG artefaktlarisiz bo'lsin.
Config.setVideoImageFormat('png');
Config.setOverwriteOutput(true);
// Deterministik: bir xil kirish -> bir xil kadrlar.
Config.setConcurrency(4);
