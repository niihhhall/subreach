import type { Lead, Message, ConversationState, LLMSession, Booking } from '../types'

export const MOCK_LEADS: Lead[] = [
    {
        id: 'mock-lead-1',
        first_name: 'Sarah',
        last_name: 'Johnson',
        email: 'sarah.j@techflow.io',
        phone: '+1 (555) 928-1234',
        company: 'TechFlow Systems',
        industry: 'SaaS',
        lead_source: 'Google',
        form_message: 'Interested in your AI automation for our customer support team.',
        temperature: 'Hot',
        outcome: 'Meeting Booked',
        signal_score: 94,
        created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
        updated_at: new Date().toISOString(),
    },
    {
        id: 'mock-lead-2',
        first_name: 'Michael',
        last_name: 'Chen',
        email: 'm.chen@vertex-solutions.com',
        phone: '+1 (555) 382-9901',
        company: 'Vertex Solutions',
        industry: 'Fintech',
        lead_source: 'Meta',
        form_message: 'Looking for a way to qualify inbound leads automatically before our sales team hops on a call.',
        temperature: 'Warm',
        outcome: 'In Progress',
        signal_score: 78,
        created_at: new Date(Date.now() - 3600000 * 5).toISOString(),
        updated_at: new Date().toISOString(),
    },
    {
        id: 'mock-lead-3',
        first_name: 'Elena',
        last_name: 'Rodriguez',
        email: 'elena@growthly.co',
        phone: '+1 (555) 123-4567',
        company: 'Growthly',
        industry: 'Marketing',
        lead_source: 'Referral',
        form_message: 'Heard about MARKEYE from a partner. We need help scaling our outbound ops.',

        temperature: 'Hot',
        outcome: 'In Progress',
        signal_score: 89,
        created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
        updated_at: new Date().toISOString(),
    },
    {
        id: 'mock-lead-4',
        first_name: 'David',
        last_name: 'Smith',
        email: 'dsmith@enterprise.com',
        phone: '+1 (555) 001-2233',
        company: 'Global Enterprise',
        industry: 'Manufacturing',
        lead_source: 'Other',
        form_message: 'Testing the waters for AI integration.',
        temperature: 'Cold',
        outcome: 'Disqualified',
        signal_score: 42,
        created_at: new Date(Date.now() - 3600000 * 48).toISOString(),
        updated_at: new Date().toISOString(),
    }
]

export const MOCK_MESSAGES: Message[] = [
    {
        id: 'm1',
        lead_id: 'mock-lead-2',
        direction: 'inbound',
        content: 'Hi, I saw your ad about AI agents. How does it work for Fintech compliance?',
        created_at: new Date(Date.now() - 600000 * 5).toISOString(),
    },
    {
        id: 'm2',
        lead_id: 'mock-lead-2',
        direction: 'outbound',
        content: "Hi Michael! Great question. Our agents can be fine-tuned with your specific compliance documentation to ensure every conversation remains within regulatory bounds while still being highly engaging.",
        created_at: new Date(Date.now() - 600000 * 4).toISOString(),
    },
    {
        id: 'm3',
        lead_id: 'mock-lead-2',
        direction: 'inbound',
        content: "That sounds promising. Can it integrate with our existing CRM?",
        created_at: new Date(Date.now() - 600000 * 3).toISOString(),
    },
    {
        id: 'm4',
        lead_id: 'mock-lead-2',
        direction: 'outbound',
        content: "Absolutely. We support native integrations with Salesforce, HubSpot, and Pipedrive, or custom webhooks for proprietary systems. Would you like to see a live integration demo?",
        created_at: new Date(Date.now() - 600000 * 2).toISOString(),
    }
]

export const MOCK_STATES: ConversationState[] = [
    {
        id: 's1',
        lead_id: 'mock-lead-2',
        current_state: 'Qualification',
        bant_budget: 'Confirmed',
        bant_authority: 'Direct',
        bant_need: 'High',
        bant_timeline: '30 days',
        message_count: 4,
        last_active_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    }
]

export const MOCK_SESSIONS: LLMSession[] = [
    {
        id: 'sess1',
        lead_id: 'mock-lead-2',
        helicone_id: 'hel_12345',
        model: 'gpt-4-turbo',
        prompt_tokens: 1240,
        completion_tokens: 432,
        total_tokens: 1672,
        cost_usd: 0.024,
        latency_ms: 1450,
        conversation_state: 'Qualification',
        created_at: new Date().toISOString(),
    }
]

export const MOCK_BOOKINGS: Booking[] = [
    {
        id: 'b1',
        lead_id: 'mock-lead-1',
        calendly_event_id: 'EVT_998877',
        scheduled_at: new Date(Date.now() + 86400000 * 2).toISOString(),
        status: 'confirmed',
        created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
    }
]
