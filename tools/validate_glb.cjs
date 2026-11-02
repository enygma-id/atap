// SPDX-License-Identifier: AGPL-3.0-only
// Pin gltf-validator to 2.0.0-dev.3.10 in the dedicated validation job.
const fs = require('fs');
const [modulePath, input, report] = process.argv.slice(2);
const validator = require(modulePath);
validator.validateBytes(new Uint8Array(fs.readFileSync(input))).then(result => {
  fs.writeFileSync(report, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result.issues));
  if (result.issues.numErrors || result.issues.numWarnings) process.exitCode = 1;
}).catch(error => { console.error(error); process.exitCode = 1; });
