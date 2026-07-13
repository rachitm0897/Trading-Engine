import type {StrategyInstance} from '../../api/types'

export function canEnable(strategy: StrategyInstance) {
  return !strategy.enabled && strategy.conid !== null && strategy.state !== 'ERROR'
}

export function canPause(strategy: StrategyInstance) {
  return strategy.enabled && strategy.state !== 'PAUSED'
}

export function canFlatten(strategy: StrategyInstance) {
  return strategy.current_target !== null && Number(strategy.current_target) !== 0
}

