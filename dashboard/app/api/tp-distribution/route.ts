import { NextResponse } from 'next/server'
import { supabase } from '@/lib/supabase'

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const daysParam = searchParams.get('days')
    const days = daysParam ? parseInt(daysParam) : undefined
    const fromParam = searchParams.get('from')
    const toParam = searchParams.get('to')

    let query = supabase
      .from('trades')
      .select('exit_reason, is_win, exit_time')
      .not('exit_time', 'is', null)

    if (fromParam && toParam) {
      query = query.gte('exit_time', `${fromParam}T00:00:00`)
      query = query.lte('exit_time', `${toParam}T23:59:59`)
    } else if (days) {
      const fromDate = new Date()
      fromDate.setDate(fromDate.getDate() - days)
      query = query.gte('exit_time', fromDate.toISOString())
    }

    const { data: trades, error } = await query

    if (error) throw error
    if (!trades || trades.length === 0) {
      return NextResponse.json([])
    }

    const total = trades.length

    const tpWins = trades.filter(t => t.exit_reason === 'tp').length
    const slLosses = trades.filter(t => t.exit_reason === 'sl').length
    const other = total - tpWins - slLosses

    const distribution = [
      {
        level: 'Take Profit',
        count: tpWins,
        percentage: (tpWins / total) * 100,
      },
      {
        level: 'Stop Loss',
        count: slLosses,
        percentage: (slLosses / total) * 100,
      },
      {
        level: 'Other',
        count: other,
        percentage: (other / total) * 100,
      },
    ].filter(d => d.count > 0)

    return NextResponse.json(distribution)
  } catch (error) {
    console.error('Failed to fetch TP distribution:', error)
    return NextResponse.json({ error: 'Failed to fetch TP distribution' }, { status: 500 })
  }
}

export const dynamic = 'force-dynamic'
export const revalidate = 0
