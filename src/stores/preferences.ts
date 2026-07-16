import {create} from 'zustand'

interface PreferencesState {
  selectedAccountId: number | null
  selectedPortfolioId: number | null
  setSelectedAccount: (id: number | null) => void
  setSelectedPortfolio: (id: number | null, accountId?: number | null) => void
}

export const usePreferencesStore = create<PreferencesState>((set) => ({
  selectedAccountId: null,
  selectedPortfolioId: null,
  setSelectedAccount: (selectedAccountId) => set({selectedAccountId}),
  setSelectedPortfolio: (selectedPortfolioId, selectedAccountId) => set((state) => ({
    selectedPortfolioId,
    selectedAccountId: selectedAccountId === undefined ? state.selectedAccountId : selectedAccountId,
  })),
}))
