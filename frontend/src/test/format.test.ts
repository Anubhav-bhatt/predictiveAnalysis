import { describe, expect, it } from 'vitest';

import { count, duration, ofExpected, percent } from '../lib/format';

/**
 * The rule these tests exist to protect: a value the backend reported as null
 * must render as "-", never as 0. Substituting a zero would invent a measurement
 * that was never taken.
 */
describe('missing values never become zero', () => {
  it('renders null percentages as a dash', () => {
    expect(percent(null)).toBe('-');
    expect(percent(undefined)).toBe('-');
    expect(percent('')).toBe('-');
    expect(percent('not-a-number')).toBe('-');
  });

  it('renders null counts as a dash', () => {
    expect(count(null)).toBe('-');
    expect(count(undefined)).toBe('-');
  });

  it('renders null durations as a dash', () => {
    expect(duration(null)).toBe('-');
    expect(duration(undefined)).toBe('-');
  });

  it('keeps a genuine zero distinct from a missing value', () => {
    expect(percent(0)).toBe('0.0%');
    expect(count(0)).toBe('0');
    expect(duration(0)).toBe('0s');
  });
});

describe('percent', () => {
  it('formats decimal strings from the API', () => {
    expect(percent('5.556', 2)).toBe('5.56%');
    expect(percent('100.000')).toBe('100.0%');
  });
});

describe('duration', () => {
  it('scales units by magnitude', () => {
    expect(duration(45)).toBe('45s');
    expect(duration(600)).toBe('10m');
    expect(duration(3660)).toBe('1h 01m');
    expect(duration(90000)).toBe('1d 1h');
  });
});

describe('ofExpected', () => {
  it('shows detected against expected topology', () => {
    expect(ofExpected(1, 2)).toBe('1 / 2');
    expect(ofExpected(4, 4)).toBe('4 / 4');
  });

  it('falls back to the bare count when no expectation is configured', () => {
    expect(ofExpected(3, null)).toBe('3');
  });

  it('reports an unknown detected count as missing', () => {
    expect(ofExpected(null, 4)).toBe('-');
  });
});
