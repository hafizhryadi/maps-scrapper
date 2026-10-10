const { getJson } = require("serpapi");
const fs = require("fs");

getJson(
  {
    engine: "google_maps",
    // sejarah, kuliner, alam, religi, belanja, hiburan, edukasi, olahraga
    q: "Wisata olahraga kota palembang",
    api_key: "ea319c478fad0455ed6012ab21b8a3c9309ed76183c60154d63f451ff0c10547",
  },
  (json) => {
    fs.writeFileSync("places_data.json", JSON.stringify(json, null, 2), "utf8");
    console.log("Result saved to places_data.json");
  }
);
