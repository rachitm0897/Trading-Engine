import {describe, expect, it} from 'vitest'

import type {GoalRecommendationRun, PortfolioGoalAllocation} from '../src/api/types'
import {goalAllowsManualEdits, recommendationBlockerText, recommendationCanBeAccepted} from '../src/features/research/recommendationState'


describe('recommendation safety state', () => {
  const run = {
    status: 'COMPLETED', accepted_at: null, expires_at: '2030-01-02T00:00:00Z', sleeves: [{id: 1}],
  } as GoalRecommendationRun

  it('only permits acceptance for completed, unexpired recommendations with sleeves', () => {
    expect(recommendationCanBeAccepted(run, new Date('2030-01-01T00:00:00Z'))).toBe(true)
    expect(recommendationCanBeAccepted({...run, status: 'RUNNING'}, new Date('2030-01-01T00:00:00Z'))).toBe(false)
    expect(recommendationCanBeAccepted({...run, sleeves: []}, new Date('2030-01-01T00:00:00Z'))).toBe(false)
    expect(recommendationCanBeAccepted(run, new Date('2030-01-03T00:00:00Z'))).toBe(false)
  })

  it('requires detach before manual editing', () => {
    expect(goalAllowsManualEdits({construction_source: 'MANUAL_OPTIMIZER'} as PortfolioGoalAllocation)).toBe(true)
    expect(goalAllowsManualEdits({construction_source: 'ACCEPTED_RECOMMENDATION'} as PortfolioGoalAllocation)).toBe(false)
  })

  it('preserves exact backend blocker codes for display', () => {
    const blocked = {...run, status: 'BLOCKED', blockers: [
      {code: 'FINNHUB_MAPPING_MISSING', message: 'AAPL has no verified mapping'},
      {code: 'IBKR_CONTRACT_NOT_QUALIFIED', message: 'JPM has no exact contract'},
    ]} as GoalRecommendationRun
    expect(recommendationBlockerText(blocked)).toContain('FINNHUB_MAPPING_MISSING: AAPL has no verified mapping')
    expect(recommendationBlockerText(blocked)).toContain('IBKR_CONTRACT_NOT_QUALIFIED: JPM has no exact contract')
  })
})
