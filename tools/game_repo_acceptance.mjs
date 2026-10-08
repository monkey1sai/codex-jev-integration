// Controller-owned acceptance independent of Worker-editable Vitest tests.
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { inflateRawSync } from 'node:zlib'

const { createZip, crc32 } = await import(pathToFileURL(resolve('scripts/zip.mjs')).href)
const entry = name => ({ name, data: Buffer.from('longdan '.repeat(100)) })
const invalid = ['', '.', '..', '../x', 'a/../x', 'a/./x', 'a//x', 'a/', '/x',
  'a\\b', 'C:x', 'C:/x', 'a\0b', '\ud800', 'a'.repeat(65536), '龍'.repeat(21846)]
for (const name of invalid) assert.throws(() => createZip([entry(name)]), `unsafe name ${JSON.stringify(name)}`)
assert.throws(() => createZip([entry('a'), entry('a')]), 'duplicate entry')
assert.throws(() => createZip([entry('\ud800'), entry('\ud801')]), 'encoded name collision')
for (const name of ['index.html', 'assets/a.js', 'models/龍膽.glb', 'a.b', 'a..b']) {
  const value = entry(name), zip = createZip([value]), length = zip.readUInt16LE(26)
  assert.equal(zip.subarray(30, 30 + length).toString(), name)
  assert.equal(zip.readUInt32LE(14), crc32(value.data))
  assert.equal(zip.readUInt16LE(8), 8)
  assert.deepEqual(inflateRawSync(zip.subarray(30 + length, 30 + length + zip.readUInt32LE(18))), value.data)
  assert.deepEqual(createZip([value]), zip)
}
for (const name of ['a'.repeat(65535), '龍'.repeat(21845)]) {
  const zip = createZip([entry(name)])
  assert.equal(zip.readUInt16LE(26), 65535, 'UTF-8 legal maximum')
}
assert.equal(createZip([]).length, 22)
console.log('GAME_ZIP_ACCEPTANCE_PASS:16_negative+2_duplicate+5_roundtrip+2_maximum+empty_archive')
