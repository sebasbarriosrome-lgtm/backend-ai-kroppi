-- Kroppi: datos preestablecidos (cultivo + 4 condiciones del café).
-- Para el esquema ya existente en Supabase (tablas crops y diseases).
-- Seguro de ejecutar más de una vez: no duplica filas.
--
-- IMPORTANTE: los textos de síntomas y recomendaciones son un BORRADOR.
-- Deben ser revisados por un agrónomo antes de mostrarse a productores.

insert into public.crops (id, name, slug, is_active, created_at)
values (gen_random_uuid(), 'Café', 'cafe', true, now())
on conflict do nothing;

insert into public.diseases
  (id, crop_id, code, name, scientific_name, pathogen_type,
   symptoms, general_recommendations, requires_agronomist, created_at)
select gen_random_uuid(), c.id, v.code, v.name, v.scientific_name, v.pathogen_type,
       v.symptoms::jsonb, v.recs::jsonb, v.requiere, now()
from public.crops c
cross join (values
  ('cafe_sano', 'Hoja sana', null, null,
   '[]',
   '["No se detectó enfermedad en esta foto. Revisa visualmente si hay síntomas."]',
   false),
  ('roya_cafe', 'Roya del café', 'Hemileia vastatrix', 'Hongo',
   '["Manchas amarillo-anaranjadas en el envés de la hoja, con aspecto polvoso."]',
   '["Consultar a un agrónomo para definir el manejo."]',
   true),
  ('phoma_cafe', 'Phoma', 'Phoma spp.', 'Hongo',
   '["Manchas oscuras necróticas en hojas jóvenes y brotes."]',
   '["Consultar a un agrónomo para definir el manejo."]',
   true),
  ('minador_cafe', 'Minador de la hoja', 'Leucoptera coffeella', 'Insecto (plaga)',
   '["Manchas irregulares y secas en la hoja, producidas por las larvas."]',
   '["Consultar a un agrónomo para definir el manejo."]',
   true)
) as v(code, name, scientific_name, pathogen_type, symptoms, recs, requiere)
where c.slug = 'cafe'
on conflict do nothing;

-- Verificación: debe devolver 4 filas
select code, name, requires_agronomist from public.diseases order by code;
