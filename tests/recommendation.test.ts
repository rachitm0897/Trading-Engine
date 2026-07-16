import {describe, expect, it} from 'vitest'

import type {GoalRecommendationRun, PortfolioGoalAllocation} from '../src/api/types'
import {goalAllowsManualEdits, recommendationCanBeAccepted} from '../src/features/research/recommendationState'


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
})
