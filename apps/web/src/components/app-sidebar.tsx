import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import {
  Activity,
  Brain,
  CheckSquare,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Plug,
  ScrollText,
} from 'lucide-react'

import { StatusDot, toneFor } from '#/components/status-badge'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '#/components/ui/sidebar'
import { api } from '#/lib/api'

const OPERATE = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/approvals', label: 'Approvals', icon: CheckSquare },
  { to: '/results', label: 'Results', icon: ListChecks },
  { to: '/activity', label: 'Activity', icon: Activity },
] as const

const CONFIGURE = [
  { to: '/rules', label: 'Rules', icon: ScrollText },
  { to: '/memory', label: 'Memory', icon: Brain },
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/settings/connections', label: 'Connections', icon: Plug },
] as const

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  // The two numbers worth carrying in the chrome: work waiting on a human, and
  // whether anything is broken. Everything else lives on its own screen.
  const dashboard = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
    refetchInterval: 60_000,
  })

  const pending = dashboard.data?.pending_approvals ?? 0
  const sources = dashboard.data?.sources ?? []
  const failing = sources.filter((s) => s.health === 'failing').length
  const health = failing > 0 ? 'failing' : sources.length ? 'ok' : undefined

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <span className="bg-ink flex size-8 shrink-0 items-center justify-center rounded-xl">
            <span className="bg-lime-accent size-3 rounded-[5px]" />
          </span>
          <div className="grid min-w-0 group-data-[collapsible=icon]:hidden">
            <span className="truncate text-sm font-bold tracking-tight">Batanat</span>
            <span className="text-muted-foreground truncate text-[11px]">agentic operations</span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Operate</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {OPERATE.map(({ to, label, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton
                    asChild
                    isActive={to === '/' ? pathname === '/' : pathname.startsWith(to)}
                    tooltip={label}
                  >
                    <Link to={to}>
                      <Icon />
                      <span>{label}</span>
                    </Link>
                  </SidebarMenuButton>
                  {label === 'Approvals' && pending > 0 && (
                    <SidebarMenuBadge className="text-status-degraded">{pending}</SidebarMenuBadge>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Configure</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {CONFIGURE.map(({ to, label, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith(to)}
                    tooltip={label}
                  >
                    <Link to={to}>
                      <Icon />
                      <span>{label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="text-muted-foreground flex items-center gap-2 px-2 py-1.5 text-[11px] group-data-[collapsible=icon]:hidden">
          <StatusDot tone={toneFor(health)} />
          {failing > 0
            ? `${failing} source${failing > 1 ? 's' : ''} failing`
            : sources.length
              ? 'All sources healthy'
              : 'No source data yet'}
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
