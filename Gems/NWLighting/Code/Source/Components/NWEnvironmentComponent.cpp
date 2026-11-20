/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#include <NWLighting/Components/NWEnvironmentComponent.h>

#include <AzCore/Component/ComponentApplicationBus.h>
#include <AzCore/Component/Entity.h>
#include <AzCore/EBus/Event.h>
#include <AtomLyIntegration/CommonFeatures/CoreLights/DirectionalLightBus.h>
#include <AtomLyIntegration/CommonFeatures/ImageBasedLights/ImageBasedLightComponentBus.h>
#include <AtomLyIntegration/CommonFeatures/ScreenSpace/DeferredFogBus.h>
#include <AzCore/Math/Quaternion.h>
#include <AzCore/Serialization/EditContext.h>
#include <AzCore/Serialization/SerializeContext.h>

namespace NWLighting
{
    void NWEnvironmentConfig::Reflect(AZ::ReflectContext* context)
    {
        if (auto* serialize = azrtti_cast<AZ::SerializeContext*>(context))
        {
            // The gem system can load the runtime module more than once;
            // register the class only the first time.
            if (serialize->FindClassData(azrtti_typeid<NWEnvironmentConfig>()))
            {
                return;
            }
            serialize->Class<NWEnvironmentConfig>()
                ->Version(1)
                ->Field("SunColor", &NWEnvironmentConfig::m_sunColor)
                ->Field("SunIntensity", &NWEnvironmentConfig::m_sunIntensity)
                ->Field("SkyColor", &NWEnvironmentConfig::m_skyColor)
                ->Field("GroundColor", &NWEnvironmentConfig::m_groundColor)
                ->Field("AmbientIntensity", &NWEnvironmentConfig::m_ambientIntensity)
                ->Field("ApplyFog", &NWEnvironmentConfig::m_applyFog)
                ->Field("FogColor", &NWEnvironmentConfig::m_fogColor)
                ->Field("FogStartDistance", &NWEnvironmentConfig::m_fogStartDistance)
                ->Field("FogEndDistance", &NWEnvironmentConfig::m_fogEndDistance)
                ->Field("IblExposure", &NWEnvironmentConfig::m_iblExposure);

            if (auto* edit = serialize->GetEditContext())
            {
                edit->Class<NWEnvironmentConfig>(
                        "New World Environment", "New World level lighting settings")
                    ->ClassElement(AZ::Edit::ClassElements::EditorData, "")
                    ->Attribute(AZ::Edit::Attributes::AutoExpand, true)
                    ->DataElement(AZ::Edit::UIHandlers::Color, &NWEnvironmentConfig::m_sunColor,
                        "Sun colour", "Colour of the directional sun light")
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentConfig::m_sunIntensity,
                        "Sun intensity", "Directional sun intensity")
                    ->Attribute(AZ::Edit::Attributes::Min, 0.0f)
                    ->DataElement(AZ::Edit::UIHandlers::Color, &NWEnvironmentConfig::m_skyColor,
                        "Sky ambient colour", "Hemisphere ambient from above")
                    ->DataElement(AZ::Edit::UIHandlers::Color, &NWEnvironmentConfig::m_groundColor,
                        "Ground bounce colour", "Hemisphere ambient from below")
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentConfig::m_ambientIntensity,
                        "Ambient intensity", "Strength of the hemisphere ambient")
                    ->Attribute(AZ::Edit::Attributes::Min, 0.0f)
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentConfig::m_applyFog,
                        "Apply fog", "Enable deferred fog for this level")
                    ->DataElement(AZ::Edit::UIHandlers::Color, &NWEnvironmentConfig::m_fogColor,
                        "Fog colour", "Deferred fog colour")
                    ->Attribute(AZ::Edit::Attributes::Visibility,
                        AZ::Edit::PropertyVisibility::ShowChildrenOnly)
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentConfig::m_fogStartDistance,
                        "Fog start", "Distance where fog begins")
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentConfig::m_fogEndDistance,
                        "Fog end", "Distance where fog is fully opaque")
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentConfig::m_iblExposure,
                        "IBL exposure", "Exposure of the image based light on this entity");
            }
        }
    }

    void NWEnvironmentComponent::Reflect(AZ::ReflectContext* context)
    {
        NWEnvironmentConfig::Reflect(context);

        if (auto* serialize = azrtti_cast<AZ::SerializeContext*>(context))
        {
            if (serialize->FindClassData(azrtti_typeid<NWEnvironmentComponent>()))
            {
                return;
            }
            serialize->Class<NWEnvironmentComponent, AZ::Component>()
                ->Version(1)
                ->Field("Configuration", &NWEnvironmentComponent::m_config);

            if (auto* edit = serialize->GetEditContext())
            {
                edit->Class<NWEnvironmentComponent>(
                        "New World Environment", "Applies New World level lighting")
                    ->ClassElement(AZ::Edit::ClassElements::EditorData, "")
                    ->Attribute(AZ::Edit::Attributes::Category, "New World")
                    ->Attribute(AZ::Edit::Attributes::AppearsInAddComponentMenu, AZ_CRC_CE("Game"))
                    ->Attribute(AZ::Edit::Attributes::AutoExpand, true)
                    ->DataElement(AZ::Edit::UIHandlers::Default, &NWEnvironmentComponent::m_config,
                        "Configuration", "New World environment settings");
            }
        }
    }

    void NWEnvironmentComponent::GetProvidedServices(AZ::ComponentDescriptor::DependencyArrayType& provided)
    {
        provided.push_back(AZ_CRC_CE("NWEnvironmentService"));
    }

    void NWEnvironmentComponent::GetIncompatibleServices(AZ::ComponentDescriptor::DependencyArrayType& incompatible)
    {
        incompatible.push_back(AZ_CRC_CE("NWEnvironmentService"));
    }

    void NWEnvironmentComponent::GetRequiredServices(AZ::ComponentDescriptor::DependencyArrayType& required)
    {
        AZ_UNUSED(required);
    }

    NWEnvironmentComponent::NWEnvironmentComponent(const NWEnvironmentConfig& config)
        : m_config(config)
    {
    }

    void NWEnvironmentComponent::Activate()
    {

        // Apply on the first tick: during level load the render scene and
        // sibling components are not necessarily ready at activation time.
        AZ::TickBus::Handler::BusConnect();
    }

    void NWEnvironmentComponent::OnTick(float deltaTime, AZ::ScriptTimePoint time)
    {
        AZ_UNUSED(deltaTime);
        AZ_UNUSED(time);
        AZ::TickBus::Handler::BusDisconnect();
        ApplyConfiguration();
    }

    void NWEnvironmentComponent::Deactivate()
    {
        AZ::TickBus::Handler::BusDisconnect();
    }

    void NWEnvironmentComponent::SetConfiguration(const NWEnvironmentConfig& config)
    {
        m_config = config;
        ApplyConfiguration();
    }

    const NWEnvironmentConfig& NWEnvironmentComponent::GetConfiguration() const
    {
        return m_config;
    }

    void NWEnvironmentComponent::ApplyConfiguration()
    {


        // Sun: drive the sibling DirectionalLightComponent when present.
        AZ::Render::DirectionalLightRequestBus::Event(
            GetEntityId(), &AZ::Render::DirectionalLightRequestBus::Events::SetColor, m_config.m_sunColor);
        AZ::Render::DirectionalLightRequestBus::Event(
            GetEntityId(),
            static_cast<void (AZ::Render::DirectionalLightRequestBus::Events::*)(float)>(
                &AZ::Render::DirectionalLightRequestBus::Events::SetIntensity),
            m_config.m_sunIntensity);

        // Image based light exposure on the same entity, when present.
        AZ::Render::ImageBasedLightComponentRequestBus::Event(
            GetEntityId(), &AZ::Render::ImageBasedLightComponentRequests::SetExposure,
            m_config.m_iblExposure);

        if (m_config.m_applyFog)
        {
            AZ::Render::DeferredFogRequestsBus::Broadcast(
                &AZ::Render::DeferredFogRequestsBus::Events::SetFogColor, m_config.m_fogColor.GetAsVector3());
            AZ::Render::DeferredFogRequestsBus::Broadcast(
                &AZ::Render::DeferredFogRequestsBus::Events::SetFogStartDistance, m_config.m_fogStartDistance);
            AZ::Render::DeferredFogRequestsBus::Broadcast(
                &AZ::Render::DeferredFogRequestsBus::Events::SetFogEndDistance, m_config.m_fogEndDistance);
        }

    }

} // namespace NWLighting
