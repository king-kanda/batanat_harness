import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { Card, CardContent, CardHeader, CardTitle } from '#/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '#/components/ui/table'
import { api, type UserServiceStats } from '#/lib/api'

export const Route = createFileRoute('/bataxxd')({ component: ServiceUserStats })

function ServiceUserStats() {
  const users = useQuery({ queryKey: ['bataxxd-users'], queryFn: api.bataxxd.users })
  const tenderCount = users.data?.[0]?.tender_catalog_count ?? 0

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Service users</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          Account activity and connected service status.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">
            {users.isPending ? 'Loading users…' : `${users.data?.length ?? 0} active users`}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {users.isError && (
            <p className="text-status-down p-6 text-sm">Could not load service user stats.</p>
          )}
          {!users.isPending && !users.isError && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Last login</TableHead>
                  <TableHead className="text-right">Emails</TableHead>
                  <TableHead className="text-right">Connections</TableHead>
                  <TableHead>Gmail</TableHead>
                  <TableHead className="text-right">Tenders</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.data?.map((user) => <UserRow key={user.id} user={user} />)}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <p className="text-muted-foreground text-xs">
        Tenders is the shared catalog count ({tenderCount.toLocaleString()}), not a per-user count.
      </p>
    </div>
  )
}

function UserRow({ user }: { user: UserServiceStats }) {
  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{user.name || 'Unnamed user'}</div>
        <div className="text-muted-foreground text-xs">{user.email}</div>
      </TableCell>
      <TableCell className="text-muted-foreground text-xs">
        {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'Never'}
      </TableCell>
      <TableCell className="text-right tabular-nums">{user.email_count}</TableCell>
      <TableCell className="text-right tabular-nums">{user.connection_count}</TableCell>
      <TableCell>
        <span className={user.gmail_connected ? 'text-status-ok' : 'text-muted-foreground'}>
          {user.gmail_connected ? 'Connected' : 'Not connected'}
        </span>
      </TableCell>
      <TableCell className="text-right tabular-nums">{user.tender_catalog_count}</TableCell>
    </TableRow>
  )
}