import {create} from 'zustand'

interface PreferencesState {
  selectedAccountId: number | null
  selectedPortfolioId: number | null
  navigationOpen: boolean
  setSelectedAccount: (id: number | null) => void
  setSelectedPortfolio: (id: number | null, accountId?: number | null) => void
  setNavigationOpen: (open: boolean) => void
}

export const usePreferencesStore = create<PreferencesState>((set) => ({
  selectedAccountId: null,
  selectedPortfolioId: null,
  navigationOpen: false,
  setSelectedAccount: (selectedAccountId) => set({selectedAccountId}),
  setSelectedPortfolio: (selectedPortfolioId, selectedAccountId) => set((state) => ({
    selectedPortfolioId,
    selectedAccountId: selectedAccountId === undefined ? state.selectedAccountId : selectedAccountId,
  })),
  setNavigationOpen: (navigationOpen) => set({navigationOpen}),
}))

