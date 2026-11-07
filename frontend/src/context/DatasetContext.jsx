import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../api/client.js'

const DatasetContext = createContext(null)
const KEY = 'ap.dataset'

const remembered = () => {
  try { return localStorage.getItem(KEY) } catch { return null }
}

export function DatasetProvider({ children }) {
  const [datasets, setDatasets] = useState([])
  const [dataset, setDatasetState] = useState(remembered())
  const [version, setVersion] = useState(0)   // bumped after a pipeline run so pages refetch
  const [error, setError] = useState(null)

  useEffect(() => {
    api.datasets()
      .then((list) => {
        setDatasets(list)
        setDatasetState((cur) => (list.some((d) => d.name === cur) ? cur : list.find((d) => d.name === 'full')?.name ?? list[0]?.name ?? null))
      })
      .catch(setError)
  }, [version])

  const setDataset = (name) => {
    setDatasetState(name)
    try { localStorage.setItem(KEY, name) } catch { /* private mode: fine */ }
  }

  return (
    <DatasetContext.Provider value={{ datasets, dataset, setDataset, version, refresh: () => setVersion((v) => v + 1), error }}>
      {children}
    </DatasetContext.Provider>
  )
}

export const useDataset = () => useContext(DatasetContext)
