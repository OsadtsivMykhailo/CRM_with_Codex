import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './api'
import AuditView from './views/AuditView.vue'
import ClientCabinetView from './views/ClientCabinetView.vue'
import ClientDetailView from './views/ClientDetailView.vue'
import ClientGroupsView from './views/ClientGroupsView.vue'
import ClientsView from './views/ClientsView.vue'
import DashboardView from './views/DashboardView.vue'
import EmployeesView from './views/EmployeesView.vue'
import CampaignsView from './views/CampaignsView.vue'
import EmailSettingsView from './views/EmailSettingsView.vue'
import SharedSendersView from './views/SharedSendersView.vue'
import SharedTemplatesView from './views/SharedTemplatesView.vue'
import SmtpSettingsView from './views/SmtpSettingsView.vue'
import LoginView from './views/LoginView.vue'
import NotificationsView from './views/NotificationsView.vue'
import RegisterView from './views/RegisterView.vue'
import RequestsView from './views/RequestsView.vue'
import UnassignedClientsView from './views/UnassignedClientsView.vue'
import UnsubscribeView from './views/UnsubscribeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/register', component: RegisterView, meta: { public: true } },
    { path: '/unsubscribe/:token', component: UnsubscribeView, meta: { public: true, allowAuthenticated: true } },
    { path: '/', component: DashboardView },
    { path: '/clients', component: ClientsView, meta: { roles: ['employee'] } },
    { path: '/clients/:id', component: ClientDetailView, meta: { roles: ['employee'] } },
    { path: '/client-groups', component: ClientGroupsView, meta: { roles: ['employee', 'admin'] } },
    { path: '/campaigns', component: CampaignsView, meta: { roles: ['employee'] } },
    { path: '/my-account', component: ClientCabinetView, meta: { roles: ['client'] } },
    { path: '/employees', component: EmployeesView, meta: { roles: ['admin'] } },
    { path: '/unassigned', component: UnassignedClientsView, meta: { roles: ['admin'] } },
    { path: '/requests', component: RequestsView, meta: { roles: ['admin'] } },
    { path: '/audit', component: AuditView, meta: { roles: ['admin'] } },
    { path: '/email-settings', component: EmailSettingsView, meta: { roles: ['admin'] } },
    { path: '/email-settings/smtp', component: SmtpSettingsView, meta: { roles: ['admin'] } },
    { path: '/email-settings/senders', component: SharedSendersView, meta: { roles: ['admin'] } },
    { path: '/email-settings/templates', component: SharedTemplatesView, meta: { roles: ['admin'] } },
    { path: '/notifications', component: NotificationsView },
  ],
})

router.beforeEach((to) => {
  const token = auth.token()
  const user = auth.user()
  if (!to.meta.public && !token) return '/login'
  if (to.meta.public && token && !to.meta.allowAuthenticated) return user?.role === 'client' ? '/my-account' : '/'
  if (to.meta.roles && user && !to.meta.roles.includes(user.role)) {
    return user.role === 'client' ? '/my-account' : '/'
  }
})

export default router
