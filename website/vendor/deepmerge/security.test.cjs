const assert = require('node:assert/strict');
const test = require('node:test');
const merge = require('./index.cjs');

test('rejects prototype keys for null-prototype targets and nested null defaults', () => {
  const source = JSON.parse('{"__proto__":{"isAdmin":true},"safe":1}');
  for (const target of [{}, Object.create(null), JSON.parse('{"__proto__":null}')]) {
    const result = merge(target, source);
    assert.equal(Object.getPrototypeOf(result), Object.prototype);
    assert.equal(result.isAdmin, undefined);
    assert.equal(Object.hasOwn(result, '__proto__'), false);
    assert.equal(result.safe, 1);
  }
  const nested = merge({session: null}, JSON.parse('{"session":{"__proto__":{"isAdmin":true}}}'));
  assert.equal(nested.session.isAdmin, undefined);
  assert.equal(Object.getPrototypeOf(nested.session), Object.prototype);
});

test('rejects forbidden keys from the target copy loop as well as the source', () => {
  const hostile = JSON.parse('{"__proto__":{"isAdmin":true},"constructor":{"prototype":{"isAdmin":true}},"prototype":{"isAdmin":true}}');
  for (const result of [merge(hostile, {}), merge({}, hostile)]) {
    assert.equal(result.isAdmin, undefined);
    assert.deepEqual(Object.keys(result), []);
    assert.equal(Object.getPrototypeOf(result), Object.prototype);
  }
  assert.equal({}.isAdmin, undefined);
});

test('preserves nested merges, merge.all, arrays, symbols, and custom merge options', () => {
  assert.deepEqual(merge.all([{nested:{a:1}}, {nested:{b:2}}]), {nested:{a:1,b:2}});
  assert.deepEqual(merge({plugins:['a']},{plugins:['b']},{arrayMerge:(_,source)=>source}), {plugins:['b']});
  assert.deepEqual(merge({plugins:['a']},{plugins:['b']}), {plugins:['a','b']});
  assert.deepEqual(merge({value:{a:1}},{value:{b:2}},{customMerge:key=>key==='value'?()=>({custom:true}):undefined}), {value:{custom:true}});
  const symbol = Symbol('config');
  assert.equal(merge({}, {[symbol]: 7})[symbol], 7);
});
