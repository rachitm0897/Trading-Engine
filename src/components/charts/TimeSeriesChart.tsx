import {useEffect, useMemo, useRef} from 'react'
import {ColorType, createChart, type IChartApi, type ISeriesApi, type SeriesMarker, type Time, type UTCTimestamp} from 'lightweight-charts'
import {EmptyState} from '../ui'

export interface ChartPoint {
  time: string
  value: number
}

export interface CandlePoint {
  time: string
  open: number
  high: number
  low: number
  close: number
}

export interface ChartLine {
  name: string
  data: ChartPoint[]
  color?: string
  type?: 'line' | 'area'
}

export interface ChartMarker {
  time: string
  label: string
  kind: 'signal' | 'target' | 'order' | 'fill'
}

const colors = ['#4676f2', '#8b5cf6', '#0d9488', '#b7791f', '#64748b']

function time(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp
}

function validTime(value: string) {
  return Number.isFinite(new Date(value).getTime())
}

function markerStyle(marker: ChartMarker): Pick<SeriesMarker<Time>, 'position' | 'shape' | 'color'> {
  if (marker.kind === 'fill') return {position: 'belowBar', shape: 'arrowUp', color: '#0d9488'}
  if (marker.kind === 'order') return {position: 'aboveBar', shape: 'circle', color: '#b7791f'}
  if (marker.kind === 'target') return {position: 'aboveBar', shape: 'square', color: '#8b5cf6'}
  return {position: 'belowBar', shape: 'arrowUp', color: '#4676f2'}
}

export function TimeSeriesChart({lines = [], candles = [], markers = [], height = 280, ariaLabel = 'Time series chart'}: {
  lines?: ChartLine[]
  candles?: CandlePoint[]
  markers?: ChartMarker[]
  height?: number
  ariaLabel?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const usableLines = useMemo(() => lines.map((line) => ({...line, data: line.data.filter((point) => validTime(point.time) && Number.isFinite(point.value))})).filter((line) => line.data.length), [lines])
  const usableCandles = useMemo(() => candles.filter((point) => validTime(point.time) && [point.open, point.high, point.low, point.close].every(Number.isFinite)), [candles])
  const hasData = usableLines.length > 0 || usableCandles.length > 0

  useEffect(() => {
    if (!container.current || !hasData) return
    const element = container.current
    const styles = getComputedStyle(document.documentElement)
    const chart: IChartApi = createChart(element, {
      height,
      width: element.clientWidth,
      layout: {background: {type: ColorType.Solid, color: 'transparent'}, textColor: styles.getPropertyValue('--text-muted').trim() || '#64748b', fontFamily: 'Inter, system-ui, sans-serif'},
      grid: {vertLines: {color: styles.getPropertyValue('--chart-grid').trim() || '#e5e7eb'}, horzLines: {color: styles.getPropertyValue('--chart-grid').trim() || '#e5e7eb'}},
      rightPriceScale: {borderColor: styles.getPropertyValue('--border').trim() || '#dfe3ea'},
      timeScale: {borderColor: styles.getPropertyValue('--border').trim() || '#dfe3ea', timeVisible: true, secondsVisible: false},
      crosshair: {vertLine: {labelBackgroundColor: '#334155'}, horzLine: {labelBackgroundColor: '#334155'}},
    })
    let markerSeries: ISeriesApi<'Candlestick'> | ISeriesApi<'Line'> | ISeriesApi<'Area'> | null = null
    if (usableCandles.length) {
      const series = chart.addCandlestickSeries({upColor: '#0d9488', downColor: '#c2414f', wickUpColor: '#0d9488', wickDownColor: '#c2414f', borderVisible: false})
      series.setData(usableCandles.map((point) => ({...point, time: time(point.time)})))
      markerSeries = series
    }
    usableLines.forEach((line, index) => {
      const color = line.color || colors[index % colors.length]
      const series = line.type === 'area'
        ? chart.addAreaSeries({lineColor: color, topColor: `${color}2f`, bottomColor: `${color}02`, lineWidth: 2, title: line.name})
        : chart.addLineSeries({color, lineWidth: 2, title: line.name})
      series.setData(line.data.map((point) => ({time: time(point.time), value: point.value})))
      if (!markerSeries) markerSeries = series
    })
    if (markerSeries && markers.length) {
      markerSeries.setMarkers(markers.filter((item) => validTime(item.time)).map((item) => ({
        time: time(item.time), text: item.label, ...markerStyle(item),
      })).sort((a, b) => Number(a.time) - Number(b.time)))
    }
    chart.timeScale().fitContent()
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => chart.applyOptions({width: element.clientWidth}))
    resize?.observe(element)
    return () => { resize?.disconnect(); chart.remove() }
  }, [hasData, height, markers, usableCandles, usableLines])

  if (!hasData) return <EmptyState title="No time-series data" description="The chart will populate from persisted market and portfolio observations." />
  return <div ref={container} className="time-series-chart" style={{height}} role="img" aria-label={ariaLabel} />
}

