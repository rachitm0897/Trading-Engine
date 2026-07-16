import {useEffect, useRef, useState, type RefObject} from 'react'
import {ColorType, createChart, type IChartApi, type MouseEventParams, type Time} from 'lightweight-charts'
import {buildChartTheme} from './chartTheme'

export function useLightweightChart(container: RefObject<HTMLDivElement>, height: number, onCrosshair: (event: MouseEventParams<Time>) => void) {
  const chartRef = useRef<IChartApi | null>(null)
  const crosshairRef = useRef(onCrosshair)
  const [ready, setReady] = useState(false)
  crosshairRef.current = onCrosshair

  useEffect(() => {
    const element = container.current
    if (!element) return
    const theme = buildChartTheme()
    const chart = createChart(element, {
      height,
      width: element.clientWidth,
      layout: {background: {type: ColorType.Solid, color: 'transparent'}, textColor: theme.text, fontFamily: '"SFMono-Regular", Consolas, monospace'},
      grid: {vertLines: {color: theme.grid}, horzLines: {color: theme.grid}},
      rightPriceScale: {borderColor: theme.border},
      timeScale: {borderColor: theme.border, timeVisible: true, secondsVisible: false, rightOffset: 4},
      crosshair: {vertLine: {color: theme.crosshair, labelBackgroundColor: theme.crosshair}, horzLine: {color: theme.crosshair, labelBackgroundColor: theme.crosshair}},
    })
    const crosshair = (event: MouseEventParams<Time>) => crosshairRef.current(event)
    chart.subscribeCrosshairMove(crosshair)
    chartRef.current = chart
    setReady(true)
    let frame = 0
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => chart.applyOptions({width: element.clientWidth}))
    })
    resize?.observe(element)
    return () => {
      cancelAnimationFrame(frame)
      resize?.disconnect()
      chart.unsubscribeCrosshairMove(crosshair)
      chart.remove()
      chartRef.current = null
    }
  }, [container])

  useEffect(() => { chartRef.current?.applyOptions({height}) }, [height])
  return {chartRef, ready}
}
