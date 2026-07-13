import {useEffect, useMemo} from 'react'
import {useQuery} from '@tanstack/react-query'
import {queries} from '../api/queries'
import {usePreferencesStore} from './preferences'

export function useSelection() {
  const accountsQuery = useQuery(queries.accounts())
  const portfoliosQuery = useQuery(queries.portfolios())
  const selectedAccountId = usePreferencesStore((state) => state.selectedAccountId)
  const selectedPortfolioId = usePreferencesStore((state) => state.selectedPortfolioId)
  const setSelectedAccount = usePreferencesStore((state) => state.setSelectedAccount)
  const setSelectedPortfolio = usePreferencesStore((state) => state.setSelectedPortfolio)

  useEffect(() => {
    const accounts = accountsQuery.data || []
    const portfolios = portfoliosQuery.data || []
    if (!selectedAccountId && accounts[0]) setSelectedAccount(accounts[0].id)
    const eligible = selectedAccountId ? portfolios.filter((portfolio) => !portfolio.account_id || portfolio.account_id === selectedAccountId) : portfolios
    if ((!selectedPortfolioId || !eligible.some((portfolio) => portfolio.id === selectedPortfolioId)) && eligible[0]) {
      setSelectedPortfolio(eligible[0].id, eligible[0].account_id ?? selectedAccountId)
    }
  }, [accountsQuery.data, portfoliosQuery.data, selectedAccountId, selectedPortfolioId, setSelectedAccount, setSelectedPortfolio])

  const accounts = accountsQuery.data || []
  const allPortfolios = portfoliosQuery.data || []
  const portfolios = useMemo(() => selectedAccountId
    ? allPortfolios.filter((portfolio) => !portfolio.account_id || portfolio.account_id === selectedAccountId)
    : allPortfolios, [allPortfolios, selectedAccountId])
  const account = accounts.find((item) => item.id === selectedAccountId) || accounts[0] || null
  const portfolio = allPortfolios.find((item) => item.id === selectedPortfolioId) || portfolios[0] || null

  return {
    accounts,
    allPortfolios,
    portfolios,
    account,
    portfolio,
    selectedAccountId: account?.id ?? null,
    selectedPortfolioId: portfolio?.id ?? null,
    setSelectedAccount,
    setSelectedPortfolio,
    loading: accountsQuery.isLoading || portfoliosQuery.isLoading,
    error: accountsQuery.error || portfoliosQuery.error,
  }
}
