import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 180000 })

export const sendMessage = (message, sessionId) =>
  http.post('/chat', { message, session_id: sessionId }).then(r => r.data)
export const listSessions = () => http.get('/sessions').then(r => r.data.sessions)
export const getSession = (id) => http.get(`/sessions/${id}`).then(r => r.data.session)
export const deleteSession = (id) => http.delete(`/sessions/${id}`).then(r => r.data)
export const clearSession = (id) => http.post(`/sessions/${id}/clear`).then(r => r.data)
export const listTickets = (status) =>
  http.get('/tickets', { params: { status } }).then(r => r.data.tickets)
export const resolveTicket = (id, human_reply) =>
  http.post(`/tickets/${id}/resolve`, { human_reply }).then(r => r.data)
