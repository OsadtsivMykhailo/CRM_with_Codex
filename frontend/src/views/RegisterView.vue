<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, auth } from '../api'

const emit = defineEmits(['authenticated'])
const router = useRouter()
const error = ref('')
const form = reactive({
  client_type: 'person', username: '', password: '', first_name: '', last_name: '', company_name: '',
  contact_person: '', email: '', phone: '', country: 'Україна', city: '', preferred_contact: 'email',
  requested_service: '', project_request: '',
  marketing_email_consent: false,
})

async function submit() {
  error.value = ''
  try {
    const data = await api('/register/', { method: 'POST', body: JSON.stringify(form) })
    auth.set(data.token, data.user)
    emit('authenticated', data.user)
    await router.push('/my-account')
  } catch (e) { error.value = e.message }
}
</script>

<template>
  <section class="auth-page single">
    <form class="form-card wide" @submit.prevent="submit">
      <p class="eyebrow">САМОСТІЙНА РЕЄСТРАЦІЯ</p><h2>Створіть анкету клієнта</h2>
      <div class="grid two">
        <label>Тип<select v-model="form.client_type"><option value="person">Фізична особа</option><option value="company">Компанія</option></select></label>
        <label>Логін<input v-model="form.username" required /></label>
        <label>Пароль<input v-model="form.password" type="password" minlength="8" required /></label>
        <label>Email<input v-model="form.email" type="email" required /></label>
        <template v-if="form.client_type === 'person'"><label>Ім’я<input v-model="form.first_name" required /></label><label>Прізвище<input v-model="form.last_name" /></label></template>
        <template v-else><label>Назва компанії<input v-model="form.company_name" required /></label><label>Контактна особа<input v-model="form.contact_person" /></label></template>
        <label>Телефон<input v-model="form.phone" required /></label><label>Місто<input v-model="form.city" required /></label>
        <label>Потрібна послуга<input v-model="form.requested_service" required /></label>
        <label>Бажаний зв’язок<select v-model="form.preferred_contact"><option value="email">Email</option><option value="phone">Телефон</option></select></label>
      </div>
      <label>Опис запиту<textarea v-model="form.project_request" rows="4" required /></label>
      <label class="checkbox consent-line"><input v-model="form.marketing_email_consent" type="checkbox" /> Я погоджуюся отримувати рекламні та інформаційні розсилки. Згоду можна відкликати в кабінеті.</label>
      <p v-if="error" class="error">{{ error }}</p><button>Створити акаунт</button>
      <RouterLink to="/login">Уже маю акаунт</RouterLink>
    </form>
  </section>
</template>
