import '@testing-library/jest-dom/vitest'
import {afterEach,vi} from 'vitest'
import {cleanup} from '@testing-library/react'
afterEach(()=>cleanup())
const series = () => ({setData: vi.fn(), setMarkers: vi.fn()})
vi.mock('lightweight-charts', () => ({ColorType: {Solid: 'Solid'}, createChart: () => ({
  addAreaSeries: series, addLineSeries: series, addCandlestickSeries: series,
  applyOptions: vi.fn(), timeScale: () => ({fitContent: vi.fn()}), remove: vi.fn(),
})}))
