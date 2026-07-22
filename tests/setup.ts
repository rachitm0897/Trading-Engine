import '@testing-library/jest-dom/vitest'
import {afterEach,vi} from 'vitest'
import {cleanup} from '@testing-library/react'
afterEach(()=>cleanup())
const series = () => ({setData: vi.fn(), update: vi.fn(), setMarkers: vi.fn(), priceScale: () => ({applyOptions: vi.fn()})})
vi.mock('lightweight-charts', () => ({
  ColorType: {Solid: 'Solid'},
  PriceScaleMode: {Normal: 0, Percentage: 2},
  createChart: () => ({
    addAreaSeries: series, addLineSeries: series, addCandlestickSeries: series, addHistogramSeries: series,
    applyOptions: vi.fn(), timeScale: () => ({fitContent: vi.fn()}), priceScale: () => ({applyOptions: vi.fn()}),
    subscribeCrosshairMove: vi.fn(), unsubscribeCrosshairMove: vi.fn(), removeSeries: vi.fn(), remove: vi.fn(),
  }),
}))
