import type {GoalRecommendationRun, PortfolioGoalAllocation} from '../../api/types'


export function recommendationCanBeAccepted(run: GoalRecommendationRun, now = new Date()) {
  return run.status === 'COMPLETED'
    && !run.accepted_at
    && new Date(run.expires_at).getTime() > now.getTime()
    && (run.sleeves?.length || 0) > 0
}


export function goalAllowsManualEdits(goal: PortfolioGoalAllocation) {
  return goal.construction_source !== 'ACCEPTED_RECOMMENDATION'
}
