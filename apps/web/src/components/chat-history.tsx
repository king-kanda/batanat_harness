import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { ChevronRight, MessageSquare, SquarePen, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '#/components/ui/collapsible'
import {
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from '#/components/ui/sidebar'
import { api } from '#/lib/api'
import { cn } from '#/lib/utils'

/** Enough to find last week's thread; past that, it is scrolling, not recall. */
const VISIBLE = 8

/**
 * Open/closed survives reloads — a sidebar that springs back open every time
 * you return is a sidebar you close twice.
 */
const OPEN_KEY = 'batanat.recent-open'

/**
 * Recent chat threads.
 *
 * The thread lives in `?c=<id>` rather than component state, which is what
 * makes these plain links: switching conversations is navigation, so Back
 * works and a thread can be pasted to someone.
 *
 * Hidden entirely when there is nothing to show. An empty "Recent" heading on
 * a first run is chrome explaining a feature you have not used yet.
 */
export function ChatHistory() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const location = useRouterState({ select: (s) => s.location })
  const activeId = new URLSearchParams(location.searchStr).get('c')
  const onChat = location.pathname === '/'

  const threads = useQuery({
    queryKey: ['conversations'],
    queryFn: api.conversations.list,
    staleTime: 30_000,
  })

  const remove = useMutation({
    mutationFn: api.conversations.remove,
    onSuccess: (_result, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      // Deleting the thread you are reading leaves the transcript orphaned on
      // screen, so drop back to a new chat.
      if (deletedId === activeId) {
        sessionStorage.removeItem('batanat.conversation')
        navigate({ to: '/', search: {}, replace: true })
      }
    },
  })

  // Default open on first visit — a collapsed section nobody has opened is a
  // feature nobody discovers.
  const [open, setOpen] = useState(true)
  useEffect(() => {
    setOpen(localStorage.getItem(OPEN_KEY) !== 'closed')
  }, [])

  const toggle = (next: boolean) => {
    setOpen(next)
    localStorage.setItem(OPEN_KEY, next ? 'open' : 'closed')
  }

  const items = threads.data ?? []
  if (items.length === 0) return null

  return (
    <Collapsible open={open} onOpenChange={toggle} className="group/recent">
      <SidebarGroup>
        <CollapsibleTrigger asChild>
          <SidebarGroupLabel
            className={cn(
              'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              'cursor-pointer rounded-md',
            )}
          >
            <ChevronRight
              className="mr-1 size-3.5 transition-transform group-data-[state=open]/recent:rotate-90 motion-reduce:transition-none"
              aria-hidden
            />
            Recent
            <span className="text-muted-foreground/70 ml-1.5 text-[10px] tabular-nums">
              {items.length}
            </span>
          </SidebarGroupLabel>
        </CollapsibleTrigger>

        {/* Outside the collapsible content: starting a new chat is the one
            thing you should not have to expand the list to reach. */}
        <SidebarGroupAction
          title="New chat"
          onClick={() => {
            sessionStorage.removeItem('batanat.conversation')
            navigate({ to: '/', search: {}, replace: true })
          }}
        >
          <SquarePen />
          <span className="sr-only">New chat</span>
        </SidebarGroupAction>

        <CollapsibleContent>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.slice(0, VISIBLE).map((thread) => (
                <SidebarMenuItem key={thread.id}>
                  <SidebarMenuButton
                    asChild
                    isActive={onChat && activeId === thread.id}
                    tooltip={thread.title}
                  >
                    <Link to="/" search={{ c: thread.id }}>
                      <MessageSquare />
                      <span className="truncate">{thread.title}</span>
                    </Link>
                  </SidebarMenuButton>
                  <SidebarMenuAction
                    showOnHover
                    onClick={() => remove.mutate(thread.id)}
                    aria-label={`Delete ${thread.title}`}
                    title="Delete"
                  >
                    <Trash2 />
                  </SidebarMenuAction>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  )
}
