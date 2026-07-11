import '@testing-library/jest-dom/vitest'
import {afterEach,vi} from 'vitest'
import {cleanup} from '@testing-library/react'
afterEach(()=>cleanup())
vi.mock('lightweight-charts',()=>({ColorType:{Solid:'Solid'},createChart:()=>({addAreaSeries:()=>({setData:vi.fn()}),timeScale:()=>({fitContent:vi.fn()}),remove:vi.fn()})}))

