const { ultraigdl } = require('ultra-igdl');

const url = process.argv[2];
if (!url) {
  console.error('Usage: node igdl_helper.js <instagram_url>');
  process.exit(1);
}

(async () => {
  try {
    const dl = new ultraigdl();
    const result = await dl.download(url);
    // Output as JSON to stdout
    process.stdout.write(JSON.stringify(result));
  } catch (err) {
    // Output error as JSON to stdout so Python can parse it
    process.stdout.write(JSON.stringify({ error: err.message }));
    process.exit(1);
  }
})();
