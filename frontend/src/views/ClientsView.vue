<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const clients = ref([])
const groups = ref([])
const error = ref('')
const showForm = ref(false)
const form = reactive({
  client_type: 'person', first_name: '', last_name: '', company_name: '', contact_person: '', email: '', phone: '',
  country: 'Україна', city: '', preferred_contact: 'email', requested_service: '', project_request: '',
  client_group_id: null,
})

async function load() {
  try { [clients.value, groups.value] = await Promise.all([api('/clients/'), api('/client-groups/')]) }
  catch (e) { error.value = e.message }
}
async function create() {
  try {
    const client = await api('/clients/', { method: 'POST', body: JSON.stringify(form) })
    await router.push(`/clients/${client.id}`)
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header">
    <div><p class="eyebrow">КЛІЄНТСЬКА БАЗА</p><h1>Доступні клієнти</h1><p>Відображаються лише анкети, до яких вам надано доступ.</p></div>
    <button @click="showForm = !showForm">+ Нова анкета</button>
  </header>
  <form v-if="showForm" class="panel grid two" @submit.prevent="create">
    <label>Тип<select v-model="form.client_type"><option value="person">Фізична особа</option><option value="company">Компанія</option></select></label>
    <label v-if="form.client_type === 'company'">Компанія<input v-model="form.company_name" required /></label>
    <label v-if="form.client_type === 'company'">Контактна особа<input v-model="form.contact_person" /></label>
    <template v-else><label>Ім’я<input v-model="form.first_name" required /></label><label>Прізвище<input v-model="form.last_name" /></label></template>
    <label>Email<input v-model="form.email" type="email" required /></label><label>Телефон<input v-model="form.phone" required /></label>
    <label>Місто<input v-model="form.city" required /></label><label>Послуга<input v-model="form.requested_service" required /></label>
    <label class="span-two">Група (необов’язково)<select v-model="form.client_group_id"><option :value="null">Без групи</option><option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option></select><small>Доступні лише групи, за які ви відповідаєте.</small></label>
    <label class="span-two">Запит<textarea v-model="form.project_request" required /></label><button>Зберегти й відкрити</button>
  </form>
  <p v-if="error" class="error">{{ error }}</p>
  <div class="table-wrap">
    <table><thead><tr><th>Клієнт</th><th>Email</th><th>Статус</th><th>Прогрес</th><th>Оновлено</th></tr></thead>
      <tbody>
        <tr v-for="client in clients" :key="client.id" class="clickable" @click="router.push(`/clients/${client.id}`)">
          <td><strong>{{ client.display_name }}</strong><small>{{ client.requested_service }}</small></td><td>{{ client.email }}</td>
          <td><span class="pill">{{ client.status }}</span></td><td>{{ client.project_progress }}%</td><td>{{ new Date(client.updated_at).toLocaleDateString('uk-UA') }}</td>
        </tr>
        <tr v-if="!clients.length"><td colspan="5" class="empty">Доступних клієнтів поки немає.</td></tr>
      </tbody>
    </table>
  </div>
</template>
