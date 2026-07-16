from django.contrib import admin

from . import models


for model in (
    models.ResearchDatasetVersion,
    models.BacktestProtocolVersion,
    models.CompatibilityRuleSet,
    models.GICSTaxonomyNode,
    models.InstrumentClassification,
    models.ResearchUniverse,
    models.ResearchUniverseMember,
    models.InstrumentEligibilitySnapshot,
    models.ResearchStrategyDefinition,
    models.ResearchFeatureDefinition,
    models.ResearchStrategyFeatureRequirement,
    models.ResearchStrategyImplementation,
    models.ResearchStrategyReadiness,
    models.ResearchDailyBar,
    models.ResearchCorporateAction,
    models.ResearchFundamentalFact,
    models.ResearchEvent,
    models.ResearchExperiment,
    models.ResearchTrial,
    models.ResearchCandidateScore,
    models.GoalRecommendationPolicy,
    models.GoalRecommendationRun,
    models.GoalRecommendationSleeve,
    models.GoalRecommendationAcceptance,
):
    admin.site.register(model)
