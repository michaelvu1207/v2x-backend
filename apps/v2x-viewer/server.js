import express from "express";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const port = Number(process.env.PORT || 3000);
const apiBaseUrl =
  process.env.API_BASE_URL || "https://qxacv7wah0.execute-api.us-west-1.amazonaws.com";

const app = express();

app.disable("x-powered-by");

app.get("/healthz", (_req, res) => {
  res.json({ ok: true });
});

app.get("/config.json", (_req, res) => {
  res.json({
    apiBaseUrl,
    routes: {
      recent: "/detections/recent",
      byObject: "/detections/object/{object_id}",
      byGeohash: "/detections/geohash/{geohash}",
    },
  });
});

app.use(express.static(path.join(__dirname, "public"), { extensions: ["html"] }));

app.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`v2x-viewer listening on :${port}`);
});

